"""
Utility functions for the Word Document Server.

This package contains utility modules for file operations and document handling.
"""

__all__ = [
    "check_file_writeable",
    "create_document_copy",
    "ensure_docx_extension",
    "find_and_replace_text",
    "insert_header_near_text",
    "insert_line_or_paragraph_near_text",
    "insert_numbered_list_near_text",
    "replace_block_between_manual_anchors",
    "replace_paragraph_block_below_header",
    "extract_document_text",
    "get_document_properties",
    "get_document_structure",
    "get_document_xml",
    "find_paragraph_by_text",
    "find_text",
    "get_paragraph_text",
]

from Agents.server.docx_use_mcp.docx_use_server.utils.file_utils import (
    check_file_writeable,
    create_document_copy,
    ensure_docx_extension,
)
from Agents.server.docx_use_mcp.docx_use_server.utils.document_utils import (
    find_and_replace_text,
    insert_header_near_text,
    insert_line_or_paragraph_near_text,
    insert_numbered_list_near_text,
    replace_block_between_manual_anchors,
    replace_paragraph_block_below_header,
    extract_document_text,
    get_document_properties,
    get_document_structure,
    get_document_xml,
    find_paragraph_by_text,
)
from Agents.server.docx_use_mcp.docx_use_server.utils.extended_document_utils import (
    find_text,
    get_paragraph_text,
)
