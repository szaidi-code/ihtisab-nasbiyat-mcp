#!/usr/bin/env python3
"""
Batch OCR & Urdu/Arabic-to-English Translation Script for Majmua Kutub Ihtisab-e-Nasbiyat.
Uses pdftoppm + Google GenAI Vision (e.g., gemini-2.5-flash) to transcribe and translate
scanned Urdu/Arabic pages into scholarly English and index them in data/ihtisab_nasbiyat.db.

Usage examples:
  export GEMINI_API_KEY="your-api-key"
  python3 batch_translate.py --book 3                    # Translate all pages of Book 3
  python3 batch_translate.py --volume 1 --start 15 --end 25  # Translate PDF pages 15-25 of Vol 1
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from server import extract_pdf_pages, get_db, save_page_translation

PROMPT = """You are an expert translator of classical Islamic Urdu and Arabic texts.
Analyze this scanned page from 'Majmua Kutub Ihtisab-e-Nasbiyat' and return a JSON object with:
{
  "text_urdu": "Complete, accurate Urdu/Arabic transcription of the page",
  "text_english": "Complete, faithful scholarly English translation of the entire page, preserving all Hadith, historical, and Rijal references",
  "summary_english": "1-2 sentence English summary of the key arguments on this page",
  "citations": "Comma-separated list of primary classical sources, books, and scholars cited on this page"
}
Return ONLY valid JSON."""


def translate_page_image(client, model: str, image_path: str) -> dict:
    from google.genai import types

    img_bytes = Path(image_path).read_bytes()
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
    return json.loads(response.text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch OCR & English translator for Ihtisab-e-Nasbiyat")
    parser.add_argument("--volume", type=int, help="Volume number (1-12)")
    parser.add_argument("--book", type=int, help="Book number (1-54)")
    parser.add_argument("--start", type=int, help="Start PDF page")
    parser.add_argument("--end", type=int, help="End PDF page")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Gemini model name")
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
        print(f"Translating Book {args.book}: {row['title_english']} (Vol {vol_num}, PDF pp. {pdf_start}-{pdf_end})")
    elif args.volume:
        vol_num = args.volume
        row = conn.execute(
            "SELECT total_pdf_pages FROM volumes WHERE volume_number = ?", (vol_num,)
        ).fetchone()
        if not row:
            raise SystemExit(f"Volume {vol_num} not found.")
        pdf_start = args.start or 1
        pdf_end = args.end or row["total_pdf_pages"]
        print(f"Translating Volume {vol_num} (PDF pp. {pdf_start}-{pdf_end})")
    else:
        raise SystemExit("Specify either --book <1-54> or --volume <1-12>.")

    conn.close()

    for p in range(pdf_start, pdf_end + 1):
        res_json = json.loads(
            extract_pdf_pages(volume_number=vol_num, start_page=p, end_page=p, page_type="pdf")
        )
        page_info = res_json["pages"][0]
        if page_info.get("cached_translation") and not args.force:
            print(f"  [Skip] Vol {vol_num} PDF p.{p} already translated.")
            continue

        print(f"  [Translating] Vol {vol_num} PDF p.{p} (Book p.{page_info['book_page']})...")
        data = translate_page_image(client, args.model, page_info["image_path"])
        save_page_translation(
            volume_number=vol_num,
            pdf_page=p,
            book_page=page_info["book_page"],
            book_number=page_info["book"]["book_number"] if page_info.get("book") else None,
            text_urdu=data.get("text_urdu", ""),
            text_english=data.get("text_english", ""),
            summary_english=data.get("summary_english", ""),
            citations=data.get("citations", ""),
        )
        time.sleep(0.5)

    print("Done!")


if __name__ == "__main__":
    main()
