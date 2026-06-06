"""
Word 文档本地工具包

将 docx_use_mcp 的 50+ 工具做成本地 Toolkit，直接调用底层逻辑，不再走 MCP HTTP。
所有工具方法都是同步的，底层 async 函数通过 asyncio.run() 调用。

与 OfficeFileManager 集成，实现用户隔离的文件路径管理。
"""

import asyncio

from agno.tools import Toolkit
from agno.tools.function import ToolResult



def _run_async(coro):
    """运行 async 函数并返回结果。如果已在事件循环中，使用 nest_asyncio 回退。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 已在异步上下文中，用 run_until_complete
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


class OfficeDocxToolkit(Toolkit):
    """
    Word 文档本地工具包。

    直接调用 docx_use_server 的底层函数，绕过 MCP HTTP。
    所有文件路径由 OfficeFileManager 管理（用户隔离）。
    """

    def __init__(self) -> None:
        super().__init__(
            name="office_docx_toolkit",
            tools=[
                # Document tools
                self.create_document,
                self.copy_document,
                self.get_document_info,
                self.get_document_text,
                self.get_document_outline,
                self.list_available_documents,
                self.merge_documents,
                # Content tools
                self.add_heading,
                self.add_paragraph,
                self.add_table,
                self.add_picture,
                self.add_page_break,
                self.delete_paragraph,
                self.search_and_replace,
                self.insert_header_near_text,
                self.insert_line_near_text,
                self.insert_numbered_list_near_text,
                self.replace_block_below_header,
                self.replace_block_between_anchors,
                # Format tools
                self.format_text,
                self.create_custom_style,
                self.format_table,
                self.set_table_cell_shading,
                self.apply_table_alternating_rows,
                self.highlight_table_header,
                self.merge_table_cells,
                self.merge_table_cells_horizontal,
                self.merge_table_cells_vertical,
                self.set_table_cell_alignment,
                self.set_table_alignment_all,
                self.set_table_column_width,
                self.set_table_column_widths,
                self.set_table_width,
                self.auto_fit_table_columns,
                self.format_table_cell_text,
                self.set_table_cell_padding,
                # Comment tools
                self.get_all_comments,
                self.get_comments_by_author,
                self.get_comments_for_paragraph,
                # Footnote tools
                self.add_footnote_to_document,
                self.add_footnote_after_text,
                self.add_footnote_before_text,
                self.add_footnote_enhanced,
                self.add_endnote_to_document,
                self.customize_footnote_style,
                self.delete_footnote_from_document,
                self.add_footnote_robust,
                self.validate_document_footnotes,
                self.delete_footnote_robust,
                # Extended tools
                self.get_paragraph_text,
                self.find_text_in_document,
                self.convert_to_pdf,
                # Protection tools
                self.protect_document,
                self.unprotect_document,
            ],
        )

    # === Helper ===

    @staticmethod
    def _import_tool(module_path: str, func_name: str):
        """延迟导入工具函数"""
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, func_name)

    def _call_tool(self, module_path: str, func_name: str, *args, **kwargs) -> str:
        """调用底层 async 工具函数并返回结果"""
        fn = self._import_tool(module_path, func_name)
        try:
            return _run_async(fn(*args, **kwargs))
        except Exception as e:
            return f"Error: {str(e)}"

    # === Document tools ===

    def create_document(self, filename: str, title: str = None, author: str = None) -> ToolResult:
        """Create a new Word document with optional metadata."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.document_tools",
            "create_document", filename, title, author
        )
        return ToolResult(content=result)

    def copy_document(self, source_filename: str, destination_filename: str = None) -> ToolResult:
        """Create a copy of a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.document_tools",
            "copy_document", source_filename, destination_filename
        )
        return ToolResult(content=result)

    def get_document_info(self, filename: str) -> ToolResult:
        """Get information about a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.document_tools",
            "get_document_info", filename
        )
        return ToolResult(content=result)

    def get_document_text(self, filename: str) -> ToolResult:
        """Extract all text from a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.document_tools",
            "get_document_text", filename
        )
        return ToolResult(content=result)

    def get_document_outline(self, filename: str) -> ToolResult:
        """Get the structure of a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.document_tools",
            "get_document_outline", filename
        )
        return ToolResult(content=result)

    def list_available_documents(self, directory: str = ".") -> ToolResult:
        """List all .docx files in the specified directory."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.document_tools",
            "list_available_documents", directory
        )
        return ToolResult(content=result)

    def merge_documents(self, target_filename: str, source_filenames: list, add_page_breaks: bool = True) -> ToolResult:
        """Merge multiple Word documents into a single document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.document_tools",
            "merge_documents", target_filename, source_filenames, add_page_breaks
        )
        return ToolResult(content=result)

    # === Content tools ===

    def add_heading(self, filename: str, text: str, level: int = 1,
                    font_name: str = None, font_size: int = None,
                    bold: bool = None, italic: bool = None, border_bottom: bool = False) -> ToolResult:
        """Add a heading to a Word document with optional formatting."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "add_heading", filename, text, level, font_name, font_size, bold, italic, border_bottom
        )
        return ToolResult(content=result)

    def add_paragraph(self, filename: str, text: str, style: str = None,
                      font_name: str = None, font_size: int = None,
                      bold: bool = None, italic: bool = None, color: str = None) -> ToolResult:
        """Add a paragraph to a Word document with optional formatting."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "add_paragraph", filename, text, style, font_name, font_size, bold, italic, color
        )
        return ToolResult(content=result)

    def add_table(self, filename: str, rows: int, cols: int, data: list = None) -> ToolResult:
        """Add a table to a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "add_table", filename, rows, cols, data
        )
        return ToolResult(content=result)

    def add_picture(self, filename: str, image_path: str, width: float = None) -> ToolResult:
        """Add an image to a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "add_picture", filename, image_path, width
        )
        return ToolResult(content=result)

    def add_page_break(self, filename: str) -> ToolResult:
        """Add a page break to the document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "add_page_break", filename
        )
        return ToolResult(content=result)

    def delete_paragraph(self, filename: str, paragraph_index: int) -> ToolResult:
        """Delete a paragraph from a document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "delete_paragraph", filename, paragraph_index
        )
        return ToolResult(content=result)

    def search_and_replace(self, filename: str, find_text: str, replace_text: str) -> ToolResult:
        """Search for text and replace all occurrences."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "search_and_replace", filename, find_text, replace_text
        )
        return ToolResult(content=result)

    def insert_header_near_text(self, filename: str, target_text: str = None,
                                header_title: str = None, position: str = 'after',
                                header_style: str = 'Heading 1',
                                target_paragraph_index: int = None) -> ToolResult:
        """Insert a header before or after the target paragraph."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "insert_header_near_text_tool", filename, target_text, header_title,
            position, header_style, target_paragraph_index
        )
        return ToolResult(content=result)

    def insert_line_near_text(self, filename: str, target_text: str = None,
                              line_text: str = None, position: str = 'after',
                              line_style: str = None,
                              target_paragraph_index: int = None) -> ToolResult:
        """Insert a new line or paragraph before or after the target paragraph."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "insert_line_or_paragraph_near_text_tool", filename, target_text,
            line_text, position, line_style, target_paragraph_index
        )
        return ToolResult(content=result)

    def insert_numbered_list_near_text(self, filename: str, target_text: str = None,
                                       list_items: list = None, position: str = 'after',
                                       target_paragraph_index: int = None,
                                       bullet_type: str = 'bullet') -> ToolResult:
        """Insert a bulleted or numbered list before or after the target paragraph."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "insert_numbered_list_near_text_tool", filename, target_text,
            list_items, position, target_paragraph_index, bullet_type
        )
        return ToolResult(content=result)

    def replace_block_below_header(self, filename: str, header_text: str,
                                   new_paragraphs: list, detect_block_end_fn: str = None) -> ToolResult:
        """Replace the block of paragraphs below a header."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "replace_paragraph_block_below_header_tool", filename, header_text,
            new_paragraphs, detect_block_end_fn
        )
        return ToolResult(content=result)

    def replace_block_between_anchors(self, filename: str, start_anchor_text: str,
                                      new_paragraphs: list, end_anchor_text: str = None,
                                      match_fn: str = None,
                                      new_paragraph_style: str = None) -> ToolResult:
        """Replace all content between start and end anchor text."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.content_tools",
            "replace_block_between_manual_anchors_tool", filename, start_anchor_text,
            new_paragraphs, end_anchor_text, match_fn, new_paragraph_style
        )
        return ToolResult(content=result)

    # === Format tools ===

    def format_text(self, filename: str, paragraph_index: int, start_pos: int, end_pos: int,
                    bold: bool = None, italic: bool = None, underline: bool = None,
                    color: str = None, font_size: int = None, font_name: str = None) -> ToolResult:
        """Format a specific range of text within a paragraph."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "format_text", filename, paragraph_index, start_pos, end_pos,
            bold, italic, underline, color, font_size, font_name
        )
        return ToolResult(content=result)

    def create_custom_style(self, filename: str, style_name: str, bold: bool = None,
                            italic: bool = None, font_size: int = None,
                            font_name: str = None, color: str = None,
                            base_style: str = None) -> ToolResult:
        """Create a custom style in the document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "create_custom_style", filename, style_name, bold, italic,
            font_size, font_name, color, base_style
        )
        return ToolResult(content=result)

    def format_table(self, filename: str, table_index: int, has_header_row: bool = None,
                     border_style: str = None, shading: list = None) -> ToolResult:
        """Format a table with borders, shading, and structure."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "format_table", filename, table_index, has_header_row, border_style, shading
        )
        return ToolResult(content=result)

    def set_table_cell_shading(self, filename: str, table_index: int, row_index: int,
                               col_index: int, fill_color: str, pattern: str = "clear") -> ToolResult:
        """Apply shading/filling to a specific table cell."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "set_table_cell_shading", filename, table_index, row_index, col_index, fill_color, pattern
        )
        return ToolResult(content=result)

    def apply_table_alternating_rows(self, filename: str, table_index: int,
                                     color1: str = "FFFFFF", color2: str = "F2F2F2") -> ToolResult:
        """Apply alternating row colors to a table."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "apply_table_alternating_rows", filename, table_index, color1, color2
        )
        return ToolResult(content=result)

    def highlight_table_header(self, filename: str, table_index: int,
                               header_color: str = "4472C4", text_color: str = "FFFFFF") -> ToolResult:
        """Apply special highlighting to table header row."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "highlight_table_header", filename, table_index, header_color, text_color
        )
        return ToolResult(content=result)

    def merge_table_cells(self, filename: str, table_index: int, start_row: int,
                          start_col: int, end_row: int, end_col: int) -> ToolResult:
        """Merge cells in a rectangular area of a table."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "merge_table_cells", filename, table_index, start_row, start_col, end_row, end_col
        )
        return ToolResult(content=result)

    def merge_table_cells_horizontal(self, filename: str, table_index: int, row_index: int,
                                     start_col: int, end_col: int) -> ToolResult:
        """Merge cells horizontally in a single row."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "merge_table_cells_horizontal", filename, table_index, row_index, start_col, end_col
        )
        return ToolResult(content=result)

    def merge_table_cells_vertical(self, filename: str, table_index: int, col_index: int,
                                   start_row: int, end_row: int) -> ToolResult:
        """Merge cells vertically in a single column."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "merge_table_cells_vertical", filename, table_index, col_index, start_row, end_row
        )
        return ToolResult(content=result)

    def set_table_cell_alignment(self, filename: str, table_index: int, row_index: int,
                                 col_index: int, horizontal: str = "left",
                                 vertical: str = "top") -> ToolResult:
        """Set text alignment for a specific table cell."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "set_table_cell_alignment", filename, table_index, row_index, col_index, horizontal, vertical
        )
        return ToolResult(content=result)

    def set_table_alignment_all(self, filename: str, table_index: int,
                                horizontal: str = "left", vertical: str = "top") -> ToolResult:
        """Set text alignment for all cells in a table."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "set_table_alignment_all", filename, table_index, horizontal, vertical
        )
        return ToolResult(content=result)

    def set_table_column_width(self, filename: str, table_index: int, col_index: int,
                               width: float, width_type: str = "points") -> ToolResult:
        """Set the width of a specific table column."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "set_table_column_width", filename, table_index, col_index, width, width_type
        )
        return ToolResult(content=result)

    def set_table_column_widths(self, filename: str, table_index: int, widths: list,
                                width_type: str = "points") -> ToolResult:
        """Set the widths of multiple table columns."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "set_table_column_widths", filename, table_index, widths, width_type
        )
        return ToolResult(content=result)

    def set_table_width(self, filename: str, table_index: int, width: float,
                        width_type: str = "points") -> ToolResult:
        """Set the overall width of a table."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "set_table_width", filename, table_index, width, width_type
        )
        return ToolResult(content=result)

    def auto_fit_table_columns(self, filename: str, table_index: int) -> ToolResult:
        """Set table columns to auto-fit based on content."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "auto_fit_table_columns", filename, table_index
        )
        return ToolResult(content=result)

    def format_table_cell_text(self, filename: str, table_index: int, row_index: int,
                               col_index: int, text_content: str = None, bold: bool = None,
                               italic: bool = None, underline: bool = None, color: str = None,
                               font_size: int = None, font_name: str = None) -> ToolResult:
        """Format text within a specific table cell."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "format_table_cell_text", filename, table_index, row_index, col_index,
            text_content, bold, italic, underline, color, font_size, font_name
        )
        return ToolResult(content=result)

    def set_table_cell_padding(self, filename: str, table_index: int, row_index: int,
                               col_index: int, top: float = None, bottom: float = None,
                               left: float = None, right: float = None,
                               unit: str = "points") -> ToolResult:
        """Set padding/margins for a specific table cell."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.format_tools",
            "set_table_cell_padding", filename, table_index, row_index, col_index,
            top, bottom, left, right, unit
        )
        return ToolResult(content=result)

    # === Comment tools ===

    def get_all_comments(self, filename: str) -> ToolResult:
        """Extract all comments from a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.comment_tools",
            "get_all_comments", filename
        )
        return ToolResult(content=result)

    def get_comments_by_author(self, filename: str, author: str) -> ToolResult:
        """Extract comments from a specific author in a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.comment_tools",
            "get_comments_by_author", filename, author
        )
        return ToolResult(content=result)

    def get_comments_for_paragraph(self, filename: str, paragraph_index: int) -> ToolResult:
        """Extract comments for a specific paragraph in a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.comment_tools",
            "get_comments_for_paragraph", filename, paragraph_index
        )
        return ToolResult(content=result)

    # === Footnote tools ===

    def add_footnote_to_document(self, filename: str, paragraph_index: int, footnote_text: str) -> ToolResult:
        """Add a footnote to a specific paragraph in a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.footnote_tools",
            "add_footnote_to_document", filename, paragraph_index, footnote_text
        )
        return ToolResult(content=result)

    def add_footnote_after_text(self, filename: str, search_text: str, footnote_text: str,
                                output_filename: str = None) -> ToolResult:
        """Add a footnote after specific text with proper superscript formatting."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.footnote_tools",
            "add_footnote_after_text", filename, search_text, footnote_text, output_filename
        )
        return ToolResult(content=result)

    def add_footnote_before_text(self, filename: str, search_text: str, footnote_text: str,
                                 output_filename: str = None) -> ToolResult:
        """Add a footnote before specific text with proper superscript formatting."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.footnote_tools",
            "add_footnote_before_text", filename, search_text, footnote_text, output_filename
        )
        return ToolResult(content=result)

    def add_footnote_enhanced(self, filename: str, paragraph_index: int, footnote_text: str,
                              output_filename: str = None) -> ToolResult:
        """Enhanced footnote addition with guaranteed superscript formatting."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.footnote_tools",
            "add_footnote_enhanced", filename, paragraph_index, footnote_text, output_filename
        )
        return ToolResult(content=result)

    def add_endnote_to_document(self, filename: str, paragraph_index: int, endnote_text: str) -> ToolResult:
        """Add an endnote to a specific paragraph in a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.footnote_tools",
            "add_endnote_to_document", filename, paragraph_index, endnote_text
        )
        return ToolResult(content=result)

    def customize_footnote_style(self, filename: str, numbering_format: str = "1, 2, 3",
                                 start_number: int = 1, font_name: str = None,
                                 font_size: int = None) -> ToolResult:
        """Customize footnote numbering and formatting in a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.footnote_tools",
            "customize_footnote_style", filename, numbering_format, start_number, font_name, font_size
        )
        return ToolResult(content=result)

    def delete_footnote_from_document(self, filename: str, footnote_id: int = None,
                                      search_text: str = None,
                                      output_filename: str = None) -> ToolResult:
        """Delete a footnote from a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.footnote_tools",
            "delete_footnote_from_document", filename, footnote_id, search_text, output_filename
        )
        return ToolResult(content=result)

    def add_footnote_robust(self, filename: str, search_text: str = None,
                            paragraph_index: int = None, footnote_text: str = "",
                            validate_location: bool = True, auto_repair: bool = False) -> ToolResult:
        """Add footnote with robust validation and Word compliance."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.footnote_tools",
            "add_footnote_robust_tool", filename, search_text, paragraph_index,
            footnote_text, validate_location, auto_repair
        )
        return ToolResult(content=result)

    def validate_document_footnotes(self, filename: str) -> ToolResult:
        """Validate all footnotes in document for coherence and compliance."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.footnote_tools",
            "validate_footnotes_tool", filename
        )
        return ToolResult(content=result)

    def delete_footnote_robust(self, filename: str, footnote_id: int = None,
                               search_text: str = None, clean_orphans: bool = True) -> ToolResult:
        """Delete footnote with comprehensive cleanup and orphan removal."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.footnote_tools",
            "delete_footnote_robust_tool", filename, footnote_id, search_text, clean_orphans
        )
        return ToolResult(content=result)

    # === Extended tools ===

    def get_paragraph_text(self, filename: str, paragraph_index: int) -> ToolResult:
        """Get text from a specific paragraph in a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.extended_document_tools",
            "get_paragraph_text_from_document", filename, paragraph_index
        )
        return ToolResult(content=result)

    def find_text_in_document(self, filename: str, text_to_find: str, match_case: bool = True,
                              whole_word: bool = False) -> ToolResult:
        """Find occurrences of specific text in a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.extended_document_tools",
            "find_text_in_document", filename, text_to_find, match_case, whole_word
        )
        return ToolResult(content=result)

    def convert_to_pdf(self, filename: str, output_filename: str = None) -> ToolResult:
        """Convert a Word document to PDF format."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.extended_document_tools",
            "convert_to_pdf", filename, output_filename
        )
        return ToolResult(content=result)

    # === Protection tools ===

    def protect_document(self, filename: str, password: str) -> ToolResult:
        """Add password protection to a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.protection_tools",
            "protect_document", filename, password
        )
        return ToolResult(content=result)

    def unprotect_document(self, filename: str, password: str) -> ToolResult:
        """Remove password protection from a Word document."""
        result = self._call_tool(
            "server.docx_use_mcp.docx_use_server.tools.protection_tools",
            "unprotect_document", filename, password
        )
        return ToolResult(content=result)
