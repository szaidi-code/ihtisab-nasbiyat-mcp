#!/usr/bin/env python3
"""
Exports a complete English translation PDF for a translated volume from data/ihtisab_nasbiyat.db.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "ihtisab_nasbiyat.db"


def add_header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(colors.HexColor("#555555"))
    canvas.drawString(
        0.65 * inch,
        10.55 * inch,
        "Majmua Kutub Ihtisab-e-Nasbiyat — Volume 1 Complete English Translation (Books 1–9)",
    )
    canvas.drawRightString(
        8.5 * inch - 0.65 * inch,
        0.45 * inch,
        f"Page {doc.page}",
    )
    canvas.setStrokeColor(colors.HexColor("#CCCCCC"))
    canvas.setLineWidth(0.5)
    canvas.line(0.65 * inch, 10.45 * inch, 8.5 * inch - 0.65 * inch, 10.45 * inch)
    canvas.line(0.65 * inch, 0.60 * inch, 8.5 * inch - 0.65 * inch, 0.60 * inch)
    canvas.restoreState()


def build_volume_pdf(vol_num: int, output_path: Path) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    vol = conn.execute("SELECT * FROM volumes WHERE volume_number = ?", (vol_num,)).fetchone()
    books = conn.execute(
        "SELECT * FROM books WHERE volume_number = ? ORDER BY book_number", (vol_num,)
    ).fetchall()
    pages = conn.execute(
        "SELECT * FROM pages WHERE volume_number = ? ORDER BY pdf_page", (vol_num,)
    ).fetchall()
    conn.close()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"Majmua Kutub Ihtisab-e-Nasbiyat - Volume {vol_num} Complete English Translation",
        author="Translated via Gemini 3.8 Flash & Indexed in Ihtisab-e-Nasbiyat MCP",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CoverTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=28,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=10,
    )
    subtitle_style = ParagraphStyle(
        "CoverSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=14,
    )
    book_header_style = ParagraphStyle(
        "BookHeader",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=20,
        textColor=colors.HexColor("#1A365D"),
        spaceBefore=10,
        spaceAfter=6,
    )
    page_header_style = ParagraphStyle(
        "PageHeader",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=8,
        spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "MetaStyle",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#4A5568"),
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "PageBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.8,
        leading=13.8,
        textColor=colors.HexColor("#1A202C"),
        spaceAfter=6,
    )

    story = []
    story.append(Spacer(1, 0.4 * inch))
    story.append(
        Paragraph(
            f"Majmua Kutub Ihtisab-e-Nasbiyat — Volume {vol_num}",
            title_style,
        )
    )
    story.append(
        Paragraph(
            f"Complete Page-by-Page Scholarly English Translation ({len(pages)} Translated Pages | {len(books)} Books)",
            subtitle_style,
        )
    )
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2B6CB0")))
    story.append(Spacer(1, 0.15 * inch))

    # Table of Books in Volume
    toc_data = [["Book #", "English Title", "Author", "Book Pages", "PDF Pages"]]
    books_by_num = {}
    for b in books:
        books_by_num[b["book_number"]] = b
        toc_data.append(
            [
                f"Book {b['book_number']}",
                Paragraph(escape(b["title_english"]), body_style),
                Paragraph(escape(b["author_english"]), body_style),
                f"pp. {b['book_start_page']}–{b['book_end_page']}",
                f"pp. {b['pdf_start_page']}–{b['pdf_end_page']}",
            ]
        )

    t = Table(toc_data, colWidths=[0.7 * inch, 2.9 * inch, 1.9 * inch, 0.85 * inch, 0.85 * inch])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFC")]),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(t)
    story.append(PageBreak())

    current_book = None
    for p in pages:
        b_num = p["book_number"]
        if b_num and b_num != current_book and b_num in books_by_num:
            current_book = b_num
            b_info = books_by_num[b_num]
            story.append(
                Paragraph(
                    f"Book {b_num}: {escape(b_info['title_english'])} ({escape(b_info['title_translit'])})",
                    book_header_style,
                )
            )
            story.append(
                Paragraph(
                    f"<b>Author:</b> {escape(b_info['author_english'])} | "
                    f"<b>Book Pages:</b> {b_info['book_start_page']}–{b_info['book_end_page']} "
                    f"(PDF pp. {b_info['pdf_start_page']}–{b_info['pdf_end_page']})",
                    meta_style,
                )
            )
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1A365D")))
            story.append(Spacer(1, 0.08 * inch))

        book_p_label = f"Book Page {p['book_page']}" if p["book_page"] and p["book_page"] > 0 else "Front Matter"
        story.append(
            Paragraph(
                f"Volume {vol_num} — PDF Page {p['pdf_page']} ({book_p_label})",
                page_header_style,
            )
        )
        if p["summary_english"]:
            story.append(
                Paragraph(
                    f"<b>Summary:</b> {escape(p['summary_english'])}",
                    meta_style,
                )
            )
        if p["citations"]:
            story.append(
                Paragraph(
                    f"<b>Citations / Sources:</b> {escape(p['citations'])}",
                    meta_style,
                )
            )

        text_eng = p["text_english"] or ""
        for para in text_eng.split("\n"):
            clean_p = para.strip()
            if clean_p:
                story.append(Paragraph(escape(clean_p), body_style))

        story.append(Spacer(1, 0.1 * inch))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0")))

    doc.build(story, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    print(f"Exported Volume {vol_num} English PDF ({len(pages)} pages) -> {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--volume", type=int, default=1)
    parser.add_argument(
        "--output",
        type=str,
        default="/home/szaidi/Downloads/Ihtisab_e_Nasbiyat_Volume_1_English_Translation.pdf",
    )
    args = parser.parse_args()
    build_volume_pdf(args.volume, Path(args.output))
