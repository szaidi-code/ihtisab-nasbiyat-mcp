#!/usr/bin/env python3
"""
Majmua Kutub Ihtisab-e-Nasbiyat (مجموعہ کتب احتساب ناصبیت) MCP Server
12 Volumes | 54 Classical & Contemporary Sunni/Deobandi Works | 2,277 Chapters (5,991 Pages)
Supports BOTH:
  1. Streamable HTTP / SSE (POST /mcp, GET /health, GET /) for Render & cloud deployment
  2. Standard Input/Output JSON-RPC (`python3 server.py --stdio`) for local MCP clients
Zero external dependencies (uses Python standard library http.server and sqlite3).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import urllib.parse
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DB_PATH", BASE_DIR / "data" / "ihtisab_nasbiyat.db"))
RENDER_DIR = BASE_DIR / "data" / "rendered_pages"
PORT = int(os.environ.get("PORT", 8080))
HOST = os.environ.get("HOST", "0.0.0.0")
VERSION = "1.0.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "MCP server for 'Majmua Kutub Ihtisab-e-Nasbiyat' (مجموعہ کتب احتساب ناصبیت) — "
    "12 volumes, 54 books, 2,277 chapters (5,991 pages). "
    "Use `search_catalog` to search in English, transliteration, or Urdu across all 54 books, "
    "2,277 translated chapter headings, scholars, and full-text translated pages. "
    "Use `list_volumes`, `list_books`, and `get_book_details` to browse the English-translated Tables of Contents."
)

TOOLS = [
    {
        "name": "list_volumes",
        "description": (
            "List all 12 volumes of Majmua Kutub Ihtisab-e-Nasbiyat with PDF filenames, page counts, "
            "book counts, chapter counts, and number of translated pages cached in the database."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_books",
        "description": (
            "List the 54 books in Ihtisab-e-Nasbiyat with English & Urdu titles, authors, page ranges, "
            "and English summaries. Optionally filter by `volume_number` (1-12) or `author_query`."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "volume_number": {
                    "type": "integer",
                    "description": "Optional volume number filter (1-12)",
                },
                "author_query": {
                    "type": "string",
                    "description": "Optional author name filter in English or Urdu (e.g. 'Nomani', 'Mazhar', 'Ibn al-Jawzi')",
                },
            },
        },
    },
    {
        "name": "get_book_details",
        "description": (
            "Get comprehensive details for a specific book (1 to 54), including its scholarly English summary, "
            "exact PDF and book page boundaries, and complete English & Urdu Table of Contents (chapters)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "book_number": {
                    "type": "integer",
                    "description": "Book number in the series (1 to 54)",
                }
            },
            "required": ["book_number"],
        },
    },
    {
        "name": "search_catalog",
        "description": (
            "Full-text search across all 12 volumes (54 books, 2,277 English & Urdu chapter headings, keywords, "
            "authors, and full-text translated pages). Supports English, Urdu, or transliterated Arabic/Urdu "
            "terms (e.g., 'Yazid', 'Constantinople', 'Karbala', 'Marwan', 'Harrah', 'Ibn al-Jawzi', 'Sahaba', 'Qisas')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query in English, transliteration, or Urdu",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results per category (default: 25)",
                    "default": 25,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "extract_pdf_pages",
        "description": (
            "Extract and render 1 to 10 pages from any volume (1-12) as individual JPEG images (when local PDFs "
            "are present) and return any cached English translation from the SQLite database for those pages."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "volume_number": {
                    "type": "integer",
                    "description": "Volume number (1 to 12)",
                },
                "start_page": {
                    "type": "integer",
                    "description": "Starting page number",
                },
                "end_page": {
                    "type": "integer",
                    "description": "Ending page number (inclusive, max 10 pages per call)",
                },
                "page_type": {
                    "type": "string",
                    "enum": ["book", "pdf"],
                    "description": "Whether start_page/end_page refer to 'book' page or 'pdf' page (default: 'book')",
                    "default": "book",
                },
                "dpi": {
                    "type": "integer",
                    "description": "Resolution in DPI when rendering local PDFs (default: 150)",
                    "default": 150,
                },
            },
            "required": ["volume_number", "start_page"],
        },
    },
    {
        "name": "save_page_translation",
        "description": (
            "Save and index the English translation (and optional Urdu transcription, summary, and citations) "
            "of a page into the permanent SQLite FTS5 database so future queries can search and retrieve it in English."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "volume_number": {"type": "integer", "description": "Volume number (1-12)"},
                "pdf_page": {"type": "integer", "description": "1-based PDF page number"},
                "text_english": {"type": "string", "description": "Full English translation of the page"},
                "book_page": {"type": "integer", "description": "Optional printed book page number"},
                "book_number": {"type": "integer", "description": "Optional book number (1-54)"},
                "text_urdu": {"type": "string", "description": "Optional Urdu/Arabic transcription"},
                "summary_english": {"type": "string", "description": "Optional 1-2 sentence English summary"},
                "citations": {"type": "string", "description": "Optional comma-separated primary sources cited"},
            },
            "required": ["volume_number", "pdf_page", "text_english"],
        },
    },
]


def get_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        import build_db
        build_db.build_database()
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS volumes (
            volume_number INTEGER PRIMARY KEY,
            pdf_filename TEXT NOT NULL,
            pdf_path TEXT NOT NULL,
            total_pdf_pages INTEGER NOT NULL,
            pdf_page_offset INTEGER NOT NULL DEFAULT 2
        );

        CREATE TABLE IF NOT EXISTS books (
            book_number INTEGER PRIMARY KEY,
            volume_number INTEGER NOT NULL,
            title_urdu TEXT NOT NULL,
            title_translit TEXT NOT NULL,
            title_english TEXT NOT NULL,
            author_urdu TEXT NOT NULL,
            author_english TEXT NOT NULL,
            book_start_page INTEGER NOT NULL,
            book_end_page INTEGER NOT NULL,
            pdf_start_page INTEGER NOT NULL,
            pdf_end_page INTEGER NOT NULL,
            summary_english TEXT NOT NULL,
            FOREIGN KEY (volume_number) REFERENCES volumes(volume_number)
        );

        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_number INTEGER NOT NULL,
            volume_number INTEGER NOT NULL,
            heading_urdu TEXT NOT NULL,
            heading_english TEXT NOT NULL,
            book_page INTEGER NOT NULL,
            pdf_page INTEGER NOT NULL,
            keywords TEXT DEFAULT '',
            FOREIGN KEY (book_number) REFERENCES books(book_number),
            FOREIGN KEY (volume_number) REFERENCES volumes(volume_number)
        );

        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            volume_number INTEGER NOT NULL,
            book_number INTEGER,
            book_page INTEGER,
            pdf_page INTEGER NOT NULL,
            text_urdu TEXT DEFAULT '',
            text_english TEXT NOT NULL,
            summary_english TEXT DEFAULT '',
            citations TEXT DEFAULT '',
            translated_at TEXT NOT NULL,
            UNIQUE(volume_number, pdf_page)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS books_fts USING fts5(
            book_number UNINDEXED,
            volume_number UNINDEXED,
            title_urdu,
            title_translit,
            title_english,
            author_urdu,
            author_english,
            summary_english
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chapters_fts USING fts5(
            chapter_id UNINDEXED,
            book_number UNINDEXED,
            volume_number UNINDEXED,
            heading_urdu,
            heading_english,
            keywords
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            page_id UNINDEXED,
            volume_number UNINDEXED,
            book_number UNINDEXED,
            pdf_page UNINDEXED,
            book_page UNINDEXED,
            text_urdu,
            text_english,
            summary_english,
            citations
        );
        """
    )
    conn.commit()


def list_volumes() -> str:
    conn = get_db()
    rows = conn.execute(
        """
        SELECT
            v.volume_number,
            v.pdf_filename,
            v.pdf_path,
            v.total_pdf_pages,
            v.pdf_page_offset,
            COUNT(DISTINCT b.book_number) AS book_count,
            (SELECT COUNT(*) FROM chapters c WHERE c.volume_number = v.volume_number) AS chapter_count,
            (SELECT COUNT(*) FROM pages p WHERE p.volume_number = v.volume_number) AS translated_page_count
        FROM volumes v
        LEFT JOIN books b ON b.volume_number = v.volume_number
        GROUP BY v.volume_number
        ORDER BY v.volume_number
        """
    ).fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    return json.dumps({"total_volumes": len(result), "volumes": result}, ensure_ascii=False, indent=2)


def list_books(
    volume_number: Optional[int] = None,
    author_query: Optional[str] = None,
) -> str:
    conn = get_db()
    sql = """
        SELECT
            b.*,
            (SELECT COUNT(*) FROM chapters c WHERE c.book_number = b.book_number) AS chapter_count
        FROM books b
        WHERE 1=1
    """
    params: list[Any] = []
    if volume_number is not None:
        sql += " AND b.volume_number = ?"
        params.append(int(volume_number))
    if author_query:
        sql += " AND (b.author_english LIKE ? OR b.author_urdu LIKE ?)"
        params.extend([f"%{author_query}%", f"%{author_query}%"])
    sql += " ORDER BY b.book_number"

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    books = [dict(r) for r in rows]
    return json.dumps({"count": len(books), "books": books}, ensure_ascii=False, indent=2)


def get_book_details(book_number: int) -> str:
    conn = get_db()
    book = conn.execute(
        """
        SELECT b.*, v.pdf_filename, v.pdf_path, v.total_pdf_pages
        FROM books b
        JOIN volumes v ON v.volume_number = b.volume_number
        WHERE b.book_number = ?
        """,
        (int(book_number),),
    ).fetchone()

    if not book:
        conn.close()
        return json.dumps({"error": f"Book number {book_number} not found (valid range: 1-54)."})

    chapters = conn.execute(
        """
        SELECT id, heading_urdu, heading_english, book_page, pdf_page, keywords
        FROM chapters
        WHERE book_number = ?
        ORDER BY pdf_page, id
        """,
        (int(book_number),),
    ).fetchall()

    translated_pages = conn.execute(
        """
        SELECT book_page, pdf_page, summary_english, translated_at
        FROM pages
        WHERE book_number = ?
        ORDER BY pdf_page
        """,
        (int(book_number),),
    ).fetchall()

    conn.close()
    data = dict(book)
    data["chapters"] = [dict(c) for c in chapters]
    data["translated_pages"] = [dict(p) for p in translated_pages]
    return json.dumps(data, ensure_ascii=False, indent=2)


def search_catalog(query: str, limit: int = 25) -> str:
    conn = get_db()
    clean_q = str(query).strip()
    limit = int(limit or 25)
    if not clean_q:
        conn.close()
        return json.dumps({"error": "Query cannot be empty."})

    tokens = [t.replace('"', "").replace("'", "") for t in clean_q.split() if t.strip()]
    fts_query = " OR ".join(f'"{t}"*' for t in tokens) if tokens else f'"{clean_q}"'
    like_pat = f"%{clean_q}%"

    book_matches = []
    try:
        rows = conn.execute(
            """
            SELECT b.book_number, b.volume_number, b.title_english, b.title_translit,
                   b.title_urdu, b.author_english, b.book_start_page, b.pdf_start_page,
                   b.summary_english
            FROM books_fts f
            JOIN books b ON b.book_number = f.book_number
            WHERE books_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
        book_matches = [dict(r) for r in rows]
    except sqlite3.Error:
        pass

    if not book_matches:
        rows = conn.execute(
            """
            SELECT book_number, volume_number, title_english, title_translit,
                   title_urdu, author_english, book_start_page, pdf_start_page,
                   summary_english
            FROM books
            WHERE title_english LIKE ? OR title_translit LIKE ? OR title_urdu LIKE ?
               OR author_english LIKE ? OR summary_english LIKE ?
            LIMIT ?
            """,
            (like_pat, like_pat, like_pat, like_pat, like_pat, limit),
        ).fetchall()
        book_matches = [dict(r) for r in rows]

    chapter_matches = []
    try:
        rows = conn.execute(
            """
            SELECT c.id AS chapter_id, c.book_number, c.volume_number,
                   b.title_english AS book_title_english, b.author_english,
                   c.heading_english, c.heading_urdu, c.book_page, c.pdf_page, c.keywords
            FROM chapters_fts f
            JOIN chapters c ON c.id = f.chapter_id
            JOIN books b ON b.book_number = c.book_number
            WHERE chapters_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
        chapter_matches = [dict(r) for r in rows]
    except sqlite3.Error:
        pass

    if not chapter_matches:
        rows = conn.execute(
            """
            SELECT c.id AS chapter_id, c.book_number, c.volume_number,
                   b.title_english AS book_title_english, b.author_english,
                   c.heading_english, c.heading_urdu, c.book_page, c.pdf_page, c.keywords
            FROM chapters c
            JOIN books b ON b.book_number = c.book_number
            WHERE c.heading_english LIKE ? OR c.heading_urdu LIKE ? OR c.keywords LIKE ?
            LIMIT ?
            """,
            (like_pat, like_pat, like_pat, limit),
        ).fetchall()
        chapter_matches = [dict(r) for r in rows]

    page_matches = []
    try:
        rows = conn.execute(
            """
            SELECT p.volume_number, p.book_number, p.book_page, p.pdf_page,
                   p.summary_english, p.citations, p.text_english, p.text_urdu
            FROM pages_fts f
            JOIN pages p ON p.id = f.page_id
            WHERE pages_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
        page_matches = [dict(r) for r in rows]
    except sqlite3.Error:
        pass

    conn.close()
    return json.dumps(
        {
            "query": query,
            "books_matched": len(book_matches),
            "chapters_matched": len(chapter_matches),
            "translated_pages_matched": len(page_matches),
            "books": book_matches,
            "chapters": chapter_matches,
            "translated_pages": page_matches,
        },
        ensure_ascii=False,
        indent=2,
    )


def extract_pdf_pages(
    volume_number: int,
    start_page: int,
    end_page: Optional[int] = None,
    page_type: str = "book",
    dpi: int = 150,
) -> str:
    volume_number = int(volume_number)
    start_page = int(start_page)
    end_page = int(end_page) if end_page is not None else start_page
    dpi = int(dpi or 150)

    if end_page < start_page:
        return json.dumps({"error": "end_page must be >= start_page"})
    if (end_page - start_page + 1) > 10:
        return json.dumps(
            {
                "error": "Maximum 10 pages can be extracted per call to protect the context window. "
                "Request a smaller range (e.g., 5-10 pages at a time)."
            }
        )

    conn = get_db()
    vol = conn.execute(
        "SELECT * FROM volumes WHERE volume_number = ?", (volume_number,)
    ).fetchone()
    if not vol:
        conn.close()
        return json.dumps({"error": f"Volume {volume_number} not found (valid: 1-12)."})

    offset = vol["pdf_page_offset"]
    total_pdf_pages = vol["total_pdf_pages"]
    pdf_path = vol["pdf_path"]

    if str(page_type).lower() == "book":
        pdf_start = start_page + offset
        pdf_end = end_page + offset
    else:
        pdf_start = start_page
        pdf_end = end_page

    pdf_start = max(1, min(total_pdf_pages, pdf_start))
    pdf_end = max(1, min(total_pdf_pages, pdf_end))

    pdf_exists_locally = Path(pdf_path).exists()
    vol_render_dir = RENDER_DIR / f"vol_{volume_number:02d}"
    if pdf_exists_locally:
        vol_render_dir.mkdir(parents=True, exist_ok=True)

    rendered_pages = []
    for p_num in range(pdf_start, pdf_end + 1):
        b_num = p_num - offset
        target_jpg = vol_render_dir / f"vol{volume_number:02d}_pdf{p_num:04d}_book{b_num:04d}.jpg"
        if pdf_exists_locally and not target_jpg.exists():
            prefix = vol_render_dir / f"tmp_p{p_num}"
            try:
                subprocess.run(
                    [
                        "pdftoppm",
                        "-jpeg",
                        "-r",
                        str(dpi),
                        "-f",
                        str(p_num),
                        "-l",
                        str(p_num),
                        "-singlefile",
                        pdf_path,
                        str(prefix),
                    ],
                    check=True,
                    capture_output=True,
                )
                tmp_jpg = Path(f"{prefix}.jpg")
                if tmp_jpg.exists():
                    tmp_jpg.rename(target_jpg)
            except Exception:
                pass

        book_row = conn.execute(
            """
            SELECT book_number, title_english, title_urdu, author_english
            FROM books
            WHERE volume_number = ? AND pdf_start_page <= ? AND pdf_end_page >= ?
            LIMIT 1
            """,
            (volume_number, p_num, p_num),
        ).fetchone()

        nearby_chapters = conn.execute(
            """
            SELECT heading_english, heading_urdu, book_page, pdf_page
            FROM chapters
            WHERE volume_number = ? AND pdf_page BETWEEN ? AND ?
            ORDER BY pdf_page
            """,
            (volume_number, p_num - 2, p_num + 2),
        ).fetchall()

        cached = conn.execute(
            """
            SELECT text_urdu, text_english, summary_english, citations, translated_at
            FROM pages
            WHERE volume_number = ? AND pdf_page = ?
            """,
            (volume_number, p_num),
        ).fetchone()

        rendered_pages.append(
            {
                "volume_number": volume_number,
                "pdf_page": p_num,
                "book_page": b_num,
                "book": dict(book_row) if book_row else None,
                "nearby_chapters": [dict(c) for c in nearby_chapters],
                "image_path": str(target_jpg) if target_jpg.exists() else None,
                "image_uri": f"file://{target_jpg}" if target_jpg.exists() else None,
                "cached_translation": dict(cached) if cached else None,
            }
        )

    conn.close()
    return json.dumps(
        {
            "volume_number": volume_number,
            "pdf_page_range": [pdf_start, pdf_end],
            "book_page_range": [pdf_start - offset, pdf_end - offset],
            "local_pdf_available": pdf_exists_locally,
            "pages": rendered_pages,
        },
        ensure_ascii=False,
        indent=2,
    )


def save_page_translation(
    volume_number: int,
    pdf_page: int,
    text_english: str,
    book_page: Optional[int] = None,
    book_number: Optional[int] = None,
    text_urdu: str = "",
    summary_english: str = "",
    citations: str = "",
) -> str:
    volume_number = int(volume_number)
    pdf_page = int(pdf_page)
    conn = get_db()
    vol = conn.execute(
        "SELECT pdf_page_offset FROM volumes WHERE volume_number = ?", (volume_number,)
    ).fetchone()
    if not vol:
        conn.close()
        return json.dumps({"error": f"Invalid volume_number {volume_number}"})

    if book_page is None:
        book_page = pdf_page - vol["pdf_page_offset"]
    else:
        book_page = int(book_page)

    if book_number is None:
        b_row = conn.execute(
            """
            SELECT book_number FROM books
            WHERE volume_number = ? AND pdf_start_page <= ? AND pdf_end_page >= ?
            LIMIT 1
            """,
            (volume_number, pdf_page, pdf_page),
        ).fetchone()
        if b_row:
            book_number = b_row["book_number"]
    else:
        book_number = int(book_number)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO pages (
            volume_number, book_number, book_page, pdf_page,
            text_urdu, text_english, summary_english, citations, translated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(volume_number, pdf_page) DO UPDATE SET
            book_number = excluded.book_number,
            book_page = excluded.book_page,
            text_urdu = CASE WHEN excluded.text_urdu != '' THEN excluded.text_urdu ELSE pages.text_urdu END,
            text_english = excluded.text_english,
            summary_english = CASE WHEN excluded.summary_english != '' THEN excluded.summary_english ELSE pages.summary_english END,
            citations = CASE WHEN excluded.citations != '' THEN excluded.citations ELSE pages.citations END,
            translated_at = excluded.translated_at
        """,
        (
            volume_number,
            book_number,
            book_page,
            pdf_page,
            text_urdu,
            text_english,
            summary_english,
            citations,
            now,
        ),
    )

    page_row = conn.execute(
        "SELECT id FROM pages WHERE volume_number = ? AND pdf_page = ?",
        (volume_number, pdf_page),
    ).fetchone()
    page_id = page_row["id"]

    conn.execute("DELETE FROM pages_fts WHERE page_id = ?", (page_id,))
    conn.execute(
        """
        INSERT INTO pages_fts (
            page_id, volume_number, book_number, pdf_page, book_page,
            text_urdu, text_english, summary_english, citations
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            page_id,
            volume_number,
            book_number,
            pdf_page,
            book_page,
            text_urdu,
            text_english,
            summary_english,
            citations,
        ),
    )
    conn.commit()
    conn.close()

    return json.dumps(
        {
            "status": "saved",
            "page_id": page_id,
            "volume_number": volume_number,
            "book_number": book_number,
            "pdf_page": pdf_page,
            "book_page": book_page,
        },
        ensure_ascii=False,
        indent=2,
    )


def execute_tool(name: str, args: dict[str, Any]) -> str:
    if name == "list_volumes":
        return list_volumes()
    elif name == "list_books":
        return list_books(
            volume_number=args.get("volume_number"),
            author_query=args.get("author_query"),
        )
    elif name == "get_book_details":
        return get_book_details(book_number=int(args["book_number"]))
    elif name == "search_catalog":
        return search_catalog(
            query=str(args["query"]),
            limit=int(args.get("limit", 25)),
        )
    elif name == "extract_pdf_pages":
        return extract_pdf_pages(
            volume_number=int(args["volume_number"]),
            start_page=int(args["start_page"]),
            end_page=int(args["end_page"]) if args.get("end_page") is not None else None,
            page_type=str(args.get("page_type", "book")),
            dpi=int(args.get("dpi", 150)),
        )
    elif name == "save_page_translation":
        return save_page_translation(
            volume_number=int(args["volume_number"]),
            pdf_page=int(args["pdf_page"]),
            text_english=str(args["text_english"]),
            book_page=int(args["book_page"]) if args.get("book_page") is not None else None,
            book_number=int(args["book_number"]) if args.get("book_number") is not None else None,
            text_urdu=str(args.get("text_urdu", "")),
            summary_english=str(args.get("summary_english", "")),
            citations=str(args.get("citations", "")),
        )
    else:
        raise ValueError(f"Unknown tool: {name}")


def handle_single_rpc(req: dict[str, Any]) -> Optional[dict[str, Any]]:
    method = req.get("method", "")
    req_id = req.get("id")

    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        params = req.get("params") or {}
        client_proto = params.get("protocolVersion", "2025-03-26")
        negotiated_proto = client_proto if client_proto in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": negotiated_proto,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "ihtisab-nasbiyat-mcp",
                    "version": VERSION,
                },
                "instructions": INSTRUCTIONS,
            },
        }
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }
    elif method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"resources": []},
        }
    elif method == "prompts/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"prompts": []},
        }
    elif method == "tools/call":
        params = req.get("params") or {}
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        try:
            text_out = execute_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": text_out,
                        }
                    ]
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(exc)},
            }
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method {method} not implemented"},
        }


def handle_rpc(body_str: str) -> Any:
    parsed = json.loads(body_str)
    if isinstance(parsed, list):
        responses = []
        for item in parsed:
            res = handle_single_rpc(item)
            if res is not None:
                responses.append(res)
        return responses if responses else None
    return handle_single_rpc(parsed)


class MCPHandler(BaseHTTPRequestHandler):
    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, Accept, Mcp-Session-Id, MCP-Protocol-Version, Last-Event-ID",
        )
        self.send_header("Access-Control-Expose-Headers", "Mcp-Session-Id, MCP-Protocol-Version")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_HEAD(self) -> None:
        self.send_response(200)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()

    def do_DELETE(self) -> None:
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        url_path = urllib.parse.urlparse(self.path).path
        accept = self.headers.get("Accept", "")

        if url_path in ("/sse", "/mcp") or (
            url_path == "/" and "text/event-stream" in accept and "text/html" not in accept
        ):
            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            endpoint_msg = "event: endpoint\ndata: /mcp\n\n"
            self.wfile.write(endpoint_msg.encode("utf-8"))
            self.wfile.flush()
            return

        if url_path in ("/", "/documentation"):
            html_file = BASE_DIR / "index.html"
            if html_file.exists():
                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_file.read_bytes())
                return

        if url_path == "/health":
            vol_count = 0
            book_count = 0
            chapter_count = 0
            page_count = 0
            try:
                conn = get_db()
                vol_count = conn.execute("SELECT COUNT(*) FROM volumes").fetchone()[0]
                book_count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
                chapter_count = conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
                page_count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
                conn.close()
            except Exception:
                pass

            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "status": "healthy",
                "service": "ihtisab-nasbiyat-mcp",
                "version": VERSION,
                "database": {
                    "volumes": vol_count,
                    "books": book_count,
                    "chapters": chapter_count,
                    "translated_pages": page_count,
                },
                "tools": [t["name"] for t in TOOLS],
                "endpoints": {
                    "mcp_rpc": "/mcp",
                    "sse": "/sse",
                    "health": "/health",
                    "docs": "/documentation",
                },
            }
            self.wfile.write(json.dumps(resp, indent=2).encode("utf-8"))
            return

        self.send_response(404)
        self._set_cors_headers()
        self.end_headers()

    def do_POST(self) -> None:
        url_path = urllib.parse.urlparse(self.path).path
        if url_path in ("/mcp", "/sse", "/"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            session_id = self.headers.get("Mcp-Session-Id") or str(uuid.uuid4())
            try:
                resp_dict = handle_rpc(body)
            except Exception as exc:
                self.send_response(400)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
                self.wfile.write(json.dumps(err).encode("utf-8"))
                return

            if resp_dict is None:
                self.send_response(202)
                self._set_cors_headers()
                self.send_header("Mcp-Session-Id", session_id)
                self.end_headers()
                return

            self.send_response(200)
            self._set_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", session_id)
            self.end_headers()
            self.wfile.write(json.dumps(resp_dict, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()


def run_stdio() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            resp = handle_rpc(line)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
            sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def main() -> None:
    if "--stdio" in sys.argv:
        run_stdio()
        return

    conn = get_db()
    conn.close()
    print(f"Starting Ihtisab-e-Nasbiyat MCP Server v{VERSION} on http://{HOST}:{PORT}")
    server = ThreadingHTTPServer((HOST, PORT), MCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
