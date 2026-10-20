# Ihtisab-e-Nasbiyat MCP Server (`ihtisab-nasbiyat`)

A Model Context Protocol (MCP) server and English/Urdu full-text search engine for **Majmua Kutub Ihtisab-e-Nasbiyat (مجموعہ کتب احتساب ناصبیت)** — the 12-volume, 54-book (5,991-page) encyclopedia refuting Nasibi and Khariji narratives regarding the Ahl al-Bayt (AS), Imam Ali (RA), Imam Hussain (RA), the tragedy of Karbala, Yazid bin Muawiya, and Marwan bin al-Hakam.

## Architecture & Hybrid Translation Pipeline

Because the 12 source PDFs in `/home/szaidi/Downloads/` are scanned Urdu/Arabic page images (totaling 5,991 pages with no embedded text layer), this MCP server uses a **3-tier hybrid architecture**:

1. **Full English & Urdu Catalog + Chapter-by-Chapter Index (`data/ihtisab_nasbiyat.db`)**
   - Every volume (1–12), every book (1–54), and all internal Tables of Contents (`فہرست` / chapter and section headings) are translated into English and indexed in a SQLite **FTS5** full-text search database (`volumes`, `books`, `chapters`, `books_fts`, `chapters_fts`).
   - Each book entry includes a scholarly English summary, author details, and exact `book_page` and `pdf_page` boundaries.
2. **Context-Safe On-Demand Page Rendering (`extract_pdf_pages`)**
   - Instead of loading a 500-page PDF into the LLM context window, `extract_pdf_pages` uses `pdftoppm` to render **only the requested 1–10 pages** as crisp 150-DPI JPEG images (`data/rendered_pages/`) and returns their local file paths alongside any cached English translations.
   - The AI agent can visually read and translate those exact pages into English on the fly and persist the translation back into the database via `save_page_translation`.
3. **Resumable Batch OCR & Translation (`batch_translate.py` & `pages_fts`)**
   - Any page translated (either interactively by the agent via `save_page_translation` or in bulk via `batch_translate.py`) is permanently stored in the `pages` and `pages_fts` tables for instant full-text English search.

## MCP Tools

- `list_volumes()`: Lists all 12 volumes, PDF paths, total pages, book/chapter counts, and cached translated page counts.
- `list_books(volume_number?, author_query?)`: Lists all 54 books with English & Urdu titles, authors, page ranges, and English summaries.
- `get_book_details(book_number)`: Returns complete book metadata, English summary, and the full English & Urdu Table of Contents (`chapters`) with exact `book_page` and `pdf_page` numbers.
- `search_catalog(query, limit=25)`: Full-text FTS5 search across all 54 books, all translated chapter/topic headings, keywords, and full-text translated pages in English, Urdu, or transliteration.
- `extract_pdf_pages(volume_number, start_page, end_page?, page_type="book", dpi=150)`: Renders 1–10 pages from a volume to individual `.jpg` files and returns their paths + any cached English translation.
- `save_page_translation(volume_number, pdf_page, text_english, ...)`: Saves and indexes an English page translation (plus optional Urdu transcription, summary, and citations) into `data/ihtisab_nasbiyat.db`.

## Commands

### Rebuild the SQLite FTS5 Database
```bash
python3 build_db.py
```

### Run the MCP Server (Stdio)
```bash
python3 server.py
```

### Run Batch OCR & English Translation (Optional)
```bash
export GEMINI_API_KEY="your-api-key"
python3 batch_translate.py --book 3
python3 batch_translate.py --volume 1 --start 15 --end 30
```
