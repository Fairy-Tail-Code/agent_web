"""
Tests for storage/file_manager.py — unified storage abstraction layer.

These tests use a temporary SQLite database and temp directories,
so they don't depend on external services.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestBaseFileManagerHelpers(unittest.TestCase):
    """Test BaseFileManager utility methods (no instantiation needed)."""

    def test_safe_user_segment_normal(self):
        from storage.file_manager import BaseFileManager
        self.assertEqual(BaseFileManager.safe_user_segment("user123"), "user123")

    def test_safe_user_segment_with_special_chars(self):
        from storage.file_manager import BaseFileManager
        result = BaseFileManager.safe_user_segment("user@domain.com")
        self.assertEqual(result, "user_domain.com")

    def test_safe_user_segment_empty(self):
        from storage.file_manager import BaseFileManager
        self.assertEqual(BaseFileManager.safe_user_segment(""), "anonymous")

    def test_safe_user_segment_none_like(self):
        from storage.file_manager import BaseFileManager
        self.assertEqual(BaseFileManager.safe_user_segment("   "), "anonymous")

    def test_safe_user_segment_strips_dots(self):
        from storage.file_manager import BaseFileManager
        result = BaseFileManager.safe_user_segment("..hidden..")
        self.assertTrue(result.startswith("hidden"))
        self.assertFalse(result.startswith("."))

    def test_sanitize_filename_normal(self):
        from storage.file_manager import BaseFileManager
        self.assertEqual(BaseFileManager.sanitize_filename("data.csv"), "data.csv")

    def test_sanitize_filename_path_traversal(self):
        """Path(foo/bar).name extracts just 'bar', so path traversal is blocked."""
        from storage.file_manager import BaseFileManager
        result = BaseFileManager.sanitize_filename("../../etc/passwd")
        self.assertEqual(result, "passwd")  # Path().name strips directory components

    def test_sanitize_filename_empty(self):
        from storage.file_manager import BaseFileManager
        result = BaseFileManager.sanitize_filename("")
        self.assertEqual(result, "unnamed")


class TestDataFileManager(unittest.TestCase):
    """Test DataFileManager with real temp directories and SQLite."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_meta.db")
        self.data_dir = os.path.join(self.tmpdir, "data")
        os.makedirs(self.data_dir, exist_ok=True)

        self.env_patcher = patch.dict(os.environ, {
            "DATA_DB_PATH": self.db_path,
            "DATA_UPLOAD_DIR": self.data_dir,
            "OSS_ENABLED": "false",
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_fm(self):
        from storage.file_manager import DataFileManager
        return DataFileManager()

    def test_table_auto_creation(self):
        """storage_files table is created on first instantiation."""
        _ = self._make_fm()  # noqa: F841 – instantiation triggers table creation
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='storage_files'")
        self.assertIsNotNone(cursor.fetchone())
        conn.close()

    def test_save_local_and_register(self):
        """save_local creates file in user dir, register writes metadata."""
        fm = self._make_fm()

        content = b"col1,col2\n1,2\n3,4\n"
        local_path = fm.save_local("user1", content, "test.csv")
        self.assertTrue(os.path.exists(local_path))
        self.assertIn("user1", local_path)

        meta = fm.register("user1", local_path, filename="test.csv", file_size=len(content))
        self.assertEqual(meta.module, "data")
        self.assertEqual(meta.filename, "test.csv")
        self.assertEqual(meta.status, "local")

    def test_get_path_returns_registered_path(self):
        """get_path retrieves the path from SQLite metadata."""
        fm = self._make_fm()
        content = b"a,b\n1,2"
        local_path = fm.save_local("user1", content, "data.csv")
        fm.register("user1", local_path, filename="data.csv")

        result = fm.get_path("user1", "data.csv")
        self.assertEqual(result, local_path)

    def test_get_csv_path_returns_latest(self):
        """get_csv_path returns the latest file for a user."""
        fm = self._make_fm()
        content1 = b"a,b\n1,2"
        path1 = fm.save_local("user1", content1, "file1.csv")
        fm.register("user1", path1, filename="file1.csv")

        import time
        time.sleep(0.01)  # ensure different timestamps

        content2 = b"a,b\n3,4"
        path2 = fm.save_local("user1", content2, "file2.csv")
        fm.register("user1", path2, filename="file2.csv")

        result = fm.get_csv_path("user1")
        self.assertEqual(result, path2)

    def test_get_path_not_found_raises(self):
        """get_path raises FileNotFoundError for unknown user."""
        fm = self._make_fm()
        with self.assertRaises(FileNotFoundError):
            fm.get_path("nonexistent_user")

    def test_register_upsert_behavior(self):
        """Registering the same filename twice updates the record."""
        fm = self._make_fm()

        content1 = b"a,b\n1,2"
        path1 = fm.save_local("user1", content1, "data.csv")
        fm.register("user1", path1, filename="data.csv")

        content2 = b"c,d\n5,6"
        path2 = fm.save_local("user1", content2, "data.csv")
        fm.register("user1", path2, filename="data.csv")

        # Should return the latest path
        result = fm.get_path("user1", "data.csv")
        self.assertEqual(result, path2)

    def test_user_isolation(self):
        """Different users get different directories."""
        fm = self._make_fm()

        path_a = fm.save_local("alice", b"a", "file.csv")
        path_b = fm.save_local("bob", b"b", "file.csv")

        self.assertNotEqual(path_a, path_b)
        self.assertIn("alice", path_a)
        self.assertIn("bob", path_b)

    def test_load_returns_content(self):
        """load() returns file bytes."""
        fm = self._make_fm()
        content = b"hello world"
        path = fm.save_local("user1", content, "test.txt")
        fm.register("user1", path, filename="test.txt")

        loaded = fm.load("user1", "test.txt")
        self.assertEqual(loaded, content)

    def test_save_local_from_path(self):
        """save_local accepts a Path source file."""
        fm = self._make_fm()

        # Create a source file
        src = os.path.join(self.tmpdir, "source.csv")
        with open(src, "w") as f:
            f.write("a,b\n1,2")

        local_path = fm.save_local("user1", Path(src), "copied.csv")
        self.assertTrue(os.path.exists(local_path))
        with open(local_path) as f:
            self.assertEqual(f.read(), "a,b\n1,2")


class TestOfficeFileManager(unittest.TestCase):
    """Test OfficeFileManager output path building."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_meta.db")
        self.office_dir = os.path.join(self.tmpdir, "office")

        self.env_patcher = patch.dict(os.environ, {
            "DATA_DB_PATH": self.db_path,
            "OFFICE_BASE_DIR": self.office_dir,
            "OSS_ENABLED": "false",
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_fm(self):
        from storage.file_manager import OfficeFileManager
        return OfficeFileManager()

    def test_build_output_path_docx(self):
        fm = self._make_fm()
        path = fm.build_output_path("user1", "report", "docx")
        self.assertTrue(path.endswith("report.docx"))
        self.assertIn("user1", path)
        self.assertIn("output", path)

    def test_build_output_path_adds_extension(self):
        fm = self._make_fm()
        path = fm.build_output_path("user1", "report", "pdf")
        self.assertTrue(path.endswith(".pdf"))

    def test_get_output_dir_creates_dir(self):
        fm = self._make_fm()
        output_dir = fm.get_output_dir("user1", "docx")
        self.assertTrue(output_dir.exists())
        self.assertTrue(str(output_dir).endswith("docx"))

    def test_module_is_office(self):
        fm = self._make_fm()
        self.assertEqual(fm.module, "office")


class TestKnowledgeFileManager(unittest.TestCase):
    """Test KnowledgeFileManager basic properties."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_meta.db")

        self.env_patcher = patch.dict(os.environ, {
            "DATA_DB_PATH": self.db_path,
            "OSS_ENABLED": "false",
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_module_is_knowledge(self):
        from storage.file_manager import KnowledgeFileManager
        fm = KnowledgeFileManager()
        self.assertEqual(fm.module, "knowledge")


class TestIsOssEnabled(unittest.TestCase):
    """Test is_oss_enabled helper."""

    def test_disabled_by_default(self):
        from storage.file_manager import is_oss_enabled
        with patch.dict(os.environ, {"OSS_ENABLED": "false"}, clear=False):
            self.assertFalse(is_oss_enabled())

    def test_enabled_but_no_config(self):
        """is_oss_enabled returns False when get_qiniu_storage raises."""
        from storage.file_manager import is_oss_enabled
        with patch.dict(os.environ, {"OSS_ENABLED": "true"}, clear=False):
            with patch("storage.get_qiniu_storage", side_effect=Exception("no config file")):
                self.assertFalse(is_oss_enabled())


if __name__ == "__main__":
    unittest.main()
