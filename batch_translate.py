#!/usr/bin/env python3
"""
Batch OCR & Urdu/Arabic-to-English Translation Script for Majmua Kutub Ihtisab-e-Nasbiyat.
Uses pdftoppm + Google GenAI Vision (gemini-3.8-flash) to transcribe and translate
scanned Urdu/Arabic pages into scholarly English and index them in data/ihtisab_nasbiyat.db.

Usage examples:
  export GEMINI_API_KEY="your-api-key"
  python3 batch_translate.py --volume 1 --workers 10
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from server import RENDER_DIR, get_db, save_page_translation

PROMPT = """You are an expert translator of classical Islamic Urdu and Arabic texts.
Analyze this scanned page from 'Majmua Kutub Ihtisab-e-Nasbiyat' and return a JSON object with:
{
  "text_urdu": "Complete, accurate Urdu/Arabic transcription of the page",
  "text_english": "Complete, faithful scholarly English translation of the entire page, preserving all Hadith, historical, and Rijal references",
  "summary_english": "1-2 sentence English summary of the key arguments on this page",
  "citations": "Comma-separated list of primary classical sources, books, and scholars cited on this page"
}
Return ONLY valid JSON."""

db_lock = threading.Lock()


def render_single_page(pdf_path: str, vol_num: int, p_num: int, b_num: int, dpi: int = 150) -> Path:
    vol_render_dir = RENDER_DIR / f"vol_{vol_num:02d}"
    vol_render_dir.mkdir(parents=True, exist_ok=True)
    target_jpg = vol_render_dir / f"vol{vol_num:02d}_pdf{p_num:04d}_book{b_num:04d}.jpg"
    if not target_jpg.exists():
        prefix = vol_render_dir / f"tmp_p{p_num}_{threading.get_ident()}"
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
    return target_jpg


def translate_page_image(client, model: str, image_path: Path) -> dict:
    from google.genai import types

    img_bytes = image_path.read_bytes()
    for attempt in range(6):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                    PROMPT,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            text = (response.text or "").strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1:
                    return json.loads(text[start : end + 1], strict=False)
                raise
        except Exception as e:
            if attempt == 5:
                raise
            wait_s = min(30, 2 ** (attempt + 1))
            print(f"    [Retry {attempt+1}/6] {image_path.name}: {e} (waiting {wait_s}s)", flush=True)
            time.sleep(wait_s)
    return {}


def process_one_page(
    client,
    model: str,
    vol_num: int,
    pdf_path: str,
    offset: int,
    p: int,
    book_num: Optional[int],
    total: int,
    counter: list,
) -> None:
    t0 = time.time()
    b_num = p - offset
    img_path = render_single_page(pdf_path, vol_num, p, b_num)
    data = translate_page_image(client, model, img_path)
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        data = {"text_english": str(data)}

    citations_val = data.get("citations", "")
    if isinstance(citations_val, list):
        citations_val = ", ".join(str(x) for x in citations_val)

    with db_lock:
        save_page_translation(
            volume_number=vol_num,
            pdf_page=p,
            book_page=b_num,
            book_number=book_num,
            text_urdu=str(data.get("text_urdu", "")),
            text_english=str(data.get("text_english", "")),
            summary_english=str(data.get("summary_english", "")),
            citations=str(citations_val),
        )
        counter[0] += 1
        elapsed = time.time() - t0
        print(
            f"  [{counter[0]}/{total}] [Saved] Vol {vol_num} PDF p.{p} (Book p.{b_num}, Book #{book_num}) in {elapsed:.1f}s",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch OCR & English translator for Ihtisab-e-Nasbiyat")
    parser.add_argument("--volume", type=int, help="Volume number (1-12)")
    parser.add_argument("--book", type=int, help="Book number (1-54)")
    parser.add_argument("--start", type=int, help="Start PDF page")
    parser.add_argument("--end", type=int, help="End PDF page")
    parser.add_argument("--model", default="gemini-3.8-flash", help="Gemini model name")
    parser.add_argument("--workers", type=int, default=10, help="Number of parallel workers")
    parser.add_argument("--force", action="store_true", help="Re-translate even if already cached")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("Error: Set GEMINI_API_KEY or GOOGLE_API_KEY environment variable first.")

    from google import genai

    client = genai.Client(api_key=api_key)
    conn = get_db()

    if args.book:
        row = conn.execute(
            "SELECT volume_number, pdf_start_page, pdf_end_page, title_english FROM books WHERE book_number = ?",
            (args.book,),
        ).fetchone()
        if not row:
            raise SystemExit(f"Book {args.book} not found.")
        vol_num = row["volume_number"]
        pdf_start = args.start or row["pdf_start_page"]
        pdf_end = args.end or row["pdf_end_page"]
        print(
            f"Translating Book {args.book}: {row['title_english']} (Vol {vol_num}, PDF pp. {pdf_start}-{pdf_end})",
            flush=True,
        )
    elif args.volume:
        vol_num = args.volume
        row = conn.execute(
            "SELECT total_pdf_pages FROM volumes WHERE volume_number = ?", (vol_num,)
        ).fetchone()
        if not row:
            raise SystemExit(f"Volume {vol_num} not found.")
        pdf_start = args.start or 1
        pdf_end = args.end or row["total_pdf_pages"]
        print(
            f"Translating Volume {vol_num} (PDF pp. {pdf_start}-{pdf_end}) with {args.workers} workers using {args.model}",
            flush=True,
        )
    else:
        raise SystemExit("Specify either --book <1-54> or --volume <1-12>.")

    vol_row = conn.execute(
        "SELECT pdf_path, pdf_page_offset FROM volumes WHERE volume_number = ?", (vol_num,)
    ).fetchone()
    pdf_path = vol_row["pdf_path"]
    offset = vol_row["pdf_page_offset"]

    book_rows = conn.execute(
        "SELECT book_number, pdf_start_page, pdf_end_page FROM books WHERE volume_number = ?",
        (vol_num,),
    ).fetchall()

    def get_book_for_page(p_num: int) -> Optional[int]:
        for b in book_rows:
            if b["pdf_start_page"] <= p_num <= b["pdf_end_page"]:
                return b["book_number"]
        return None

    cached_pages = set()
    if not args.force:
        cached_rows = conn.execute(
            "SELECT pdf_page FROM pages WHERE volume_number = ? AND length(trim(text_english)) > 10",
            (vol_num,),
        ).fetchall()
        cached_pages = {r["pdf_page"] for r in cached_rows}

    conn.close()

    all_pages = list(range(pdf_start, pdf_end + 1))
    todo_pages = [p for p in all_pages if p not in cached_pages]
    print(
        f"Total pages in range: {len(all_pages)} | Already cached: {len(all_pages) - len(todo_pages)} | Remaining to translate: {len(todo_pages)}",
        flush=True,
    )

    if not todo_pages:
        print("All requested pages are already translated!", flush=True)
        return

    total = len(todo_pages)
    counter = [0]
    t_start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_one_page,
                client,
                args.model,
                vol_num,
                pdf_path,
                offset,
                p,
                get_book_for_page(p),
                total,
                counter,
            ): p
            for p in todo_pages
        }
        failed = []
        for fut in concurrent.futures.as_completed(futures):
            p = futures[fut]
            try:
                fut.result()
            except Exception as e:
                print(f"  [Error] Vol {vol_num} PDF p.{p} failed: {e}", flush=True)
                failed.append(p)

    elapsed_total = time.time() - t_start
    print(
        f"Done! Completed {total - len(failed)}/{total} pages in {elapsed_total:.1f}s ({elapsed_total/60:.1f} min). Failed: {len(failed)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
