#!/usr/bin/env python3
"""
Builds data/ihtisab_nasbiyat.db (SQLite + FTS5) and data/catalog.json from the
extracted volume JSON files. Preserves any existing full-page translations in `pages`.
"""

from __future__ import annotations

import glob
import json
import sqlite3
from pathlib import Path

from server import DB_PATH, init_schema

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CATALOG_JSON = DATA_DIR / "catalog.json"
SCRATCH_DIR = Path("/home/szaidi/.gemini/antigravity/brain/c54a8806-210c-47eb-9a2d-c424626d9d0f/scratch")


def load_source_volumes() -> list[dict]:
    volumes_by_num: dict[int, dict] = {}

    if CATALOG_JSON.exists():
        with open(CATALOG_JSON, "r", encoding="utf-8") as f:
            existing = json.load(f)
            for v in existing.get("volumes", []):
                volumes_by_num[v["volume_number"]] = v

    for jf in sorted(glob.glob(str(SCRATCH_DIR / "vol_*.json"))):
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
            for v in data.get("volumes", []):
                volumes_by_num[v["volume_number"]] = v
        except Exception as exc:
            print(f"Warning: failed reading {jf}: {exc}")

    return [volumes_by_num[k] for k in sorted(volumes_by_num.keys())]


def build_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    volumes = load_source_volumes()
    if not volumes:
        raise RuntimeError("No volume JSON data found to build database.")

    with open(CATALOG_JSON, "w", encoding="utf-8") as f:
        json.dump({"volumes": volumes}, f, ensure_ascii=False, indent=2)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    init_schema(conn)

    # Clear catalog tables (preserve `pages` and `pages_fts` so cached page translations are never lost)
    conn.executescript(
        """
        DELETE FROM chapters_fts;
        DELETE FROM books_fts;
        DELETE FROM chapters;
        DELETE FROM books;
        DELETE FROM volumes;
        """
    )

    total_books = 0
    total_chapters = 0

    for vol in volumes:
        v_num = int(vol["volume_number"])
        offset = int(vol.get("pdf_page_offset", 2))
        pdf_path = vol.get("pdf_path") or f"/home/szaidi/Downloads/{vol['pdf_filename']}"
        vol["pdf_path"] = pdf_path
        conn.execute(
            """
            INSERT INTO volumes (volume_number, pdf_filename, pdf_path, total_pdf_pages, pdf_page_offset)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                v_num,
                vol["pdf_filename"],
                pdf_path,
                int(vol["total_pdf_pages"]),
                offset,
            ),
        )

        for book in vol.get("books", []):
            b_num = int(book.get("book_number") or book.get("book_number_in_series"))
            book["book_number"] = b_num
            book["volume_number"] = v_num
            title_translit = book.get("title_translit") or book.get("title_transliterated", "")
            book["title_translit"] = title_translit
            b_start = int(book["book_start_page"])
            b_end = int(book["book_end_page"])
            p_start = int(book.get("pdf_start_page", b_start + offset))
            p_end = int(book.get("pdf_end_page", b_end + offset))

            conn.execute(
                """
                INSERT INTO books (
                    book_number, volume_number, title_urdu, title_translit, title_english,
                    author_urdu, author_english, book_start_page, book_end_page,
                    pdf_start_page, pdf_end_page, summary_english
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    b_num,
                    v_num,
                    book["title_urdu"],
                    title_translit,
                    book["title_english"],
                    book["author_urdu"],
                    book["author_english"],
                    b_start,
                    b_end,
                    p_start,
                    p_end,
                    book.get("summary_english", ""),
                ),
            )

            conn.execute(
                """
                INSERT INTO books_fts (
                    book_number, volume_number, title_urdu, title_translit, title_english,
                    author_urdu, author_english, summary_english
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    b_num,
                    v_num,
                    book["title_urdu"],
                    title_translit,
                    book["title_english"],
                    book["author_urdu"],
                    book["author_english"],
                    book.get("summary_english", ""),
                ),
            )
            total_books += 1

            for ch in book.get("chapters", []):
                c_bpage = int(ch.get("book_page", b_start))
                c_ppage = int(ch.get("pdf_page", c_bpage + offset))
                h_urdu = ch.get("heading_urdu") or ch.get("chapter_urdu") or ch.get("title_urdu", "")
                h_eng = ch.get("heading_english") or ch.get("chapter_english") or ch.get("title_english", "")
                ch["heading_urdu"] = h_urdu
                ch["heading_english"] = h_eng
                kw_raw = ch.get("keywords", "")
                kw_str = ", ".join(str(x) for x in kw_raw) if isinstance(kw_raw, list) else str(kw_raw or "")
                ch["keywords"] = kw_str
                cur = conn.execute(
                    """
                    INSERT INTO chapters (
                        book_number, volume_number, heading_urdu, heading_english,
                        book_page, pdf_page, keywords
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        b_num,
                        v_num,
                        h_urdu,
                        h_eng,
                        c_bpage,
                        c_ppage,
                        kw_str,
                    ),
                )
                ch_id = cur.lastrowid
                conn.execute(
                    """
                    INSERT INTO chapters_fts (
                        chapter_id, book_number, volume_number,
                        heading_urdu, heading_english, keywords
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ch_id,
                        b_num,
                        v_num,
                        h_urdu,
                        h_eng,
                        kw_str,
                    ),
                )
                total_chapters += 1

    conn.commit()
    conn.close()
    print(
        f"Database built successfully at {DB_PATH}: "
        f"{len(volumes)} volumes, {total_books} books, {total_chapters} chapters indexed."
    )


if __name__ == "__main__":
    build_database()
