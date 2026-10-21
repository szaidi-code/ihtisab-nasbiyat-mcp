#!/usr/bin/env python3
"""
Exports a complete, 100% human-readable English translation PDF for a translated volume
from data/ihtisab_nasbiyat.db using embedded TrueType Unicode fonts (Liberation Sans)
and clean ASCII-friendly English transliteration (no missing glyph boxes ■).
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import unicodedata
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
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

# Register TrueType fonts so ReportLab never produces ■ missing-glyph boxes
FONT_DIR = Path("/usr/share/fonts/truetype/liberation")
if (FONT_DIR / "LiberationSans-Regular.ttf").exists():
    pdfmetrics.registerFont(TTFont("LibSans", str(FONT_DIR / "LiberationSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("LibSans-Bold", str(FONT_DIR / "LiberationSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("LibSans-Italic", str(FONT_DIR / "LiberationSans-Italic.ttf")))
    pdfmetrics.registerFont(TTFont("LibSans-BoldItalic", str(FONT_DIR / "LiberationSans-BoldItalic.ttf")))
    pdfmetrics.registerFontFamily(
        "LibSans",
        normal="LibSans",
        bold="LibSans-Bold",
        italic="LibSans-Italic",
        boldItalic="LibSans-BoldItalic",
    )
    FONT_REGULAR = "LibSans"
    FONT_BOLD = "LibSans-Bold"
    FONT_ITALIC = "LibSans-Italic"
else:
    FONT_REGULAR = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"
    FONT_ITALIC = "Helvetica-Oblique"

ARABIC_PHRASE_MAP = {
    "ﷺ": "(peace be upon him)",
    "رحمه الله": "may Allah have mercy on him",
    "رضي الله عنه": "may Allah be pleased with him",
    "أقوام يقادون إلى الجنة بالسلاسل": "Aqwam yuqaduna ila al-Jannah bi-al-salasil",
    "واقع الله له في القلوب القبول والهيبة وكان زاهداً في الدنيا متقللاً منها.": (
        "Wa alqa Allahu lahu fi al-qulub al-qabul wa al-haybah wa kana zahidan fi al-dunya mutaqallilan minha."
    ),
    "واقع الله له في القلوب القبول والهيبة وكان زاهداً في الدنيا متقللاً منها": (
        "Wa alqa Allahu lahu fi al-qulub al-qabul wa al-haybah wa kana zahidan fi al-dunya mutaqallilan minha"
    ),
    "ما مازح قط ولا لعب مع صبي ولا أكل من جهة لا يتيقن حلها.": (
        "Ma mazaha qattu wa la la'iba ma'a sabiyyin wa la akala min jihatin la yatayaqqanu hillaha."
    ),
    "ما مازح قط ولا لعب مع صبي ولا أكل من جهة لا يتيقن حلها": (
        "Ma mazaha qattu wa la la'iba ma'a sabiyyin wa la akala min jihatin la yatayaqqanu hillaha"
    ),
    "اللهم إني أستودعك إياهم وصالح المؤمنين": "Allahumma inni astawdi'uka iyyahum wa salih al-mu'minin",
    "أُرِيدُ حَيَاتَهُ وَيُرِيدُ قَتْلِي": "Uridu hayatahu wa yuridu qatli",
    " (ابن کثیر)": "",
    " (تاریخ الخلفاء للسیوطی)": "",
    " (مفتی محمد شفیع عثمانی)": "",
    " (کامل ابن اثیر)": "",
}

CHAR_MAP = str.maketrans(
    {
        "ā": "a",
        "Ā": "A",
        "ī": "i",
        "Ī": "I",
        "ū": "u",
        "Ū": "U",
        "ḥ": "h",
        "Ḥ": "H",
        "ṣ": "s",
        "Ṣ": "S",
        "ḍ": "d",
        "Ḍ": "D",
        "ṭ": "t",
        "Ṭ": "T",
        "ẓ": "z",
        "Ẓ": "Z",
        "ṉ": "n",
        "Ṉ": "N",
        "ʿ": "'",
        "ʾ": "'",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "☆": "*",
        "❖": "-",
    }
)


def clean_human_readable_english(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    for k, v in ARABIC_PHRASE_MAP.items():
        s = s.replace(k, v)
    s = s.translate(CHAR_MAP)
    # Strip any remaining combining diacritical marks (macrons, dots below, etc.)
    nfkd = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    # Remove any stray Arabic/Urdu script characters from English fields
    s = re.sub(r"\s*\([\u0600-\u06FF\s]+\)", "", s)
    s = re.sub(r"[\u0600-\u06FF]+", "", s)
    return s.strip()


def sanitize_database(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Clean pages
    rows = conn.execute("SELECT id, text_english, summary_english, citations FROM pages").fetchall()
    for r in rows:
        conn.execute(
            "UPDATE pages SET text_english = ?, summary_english = ?, citations = ? WHERE id = ?",
            (
                clean_human_readable_english(r["text_english"]),
                clean_human_readable_english(r["summary_english"]),
                clean_human_readable_english(r["citations"]),
                r["id"],
            ),
        )

    # Clean books
    b_rows = conn.execute(
        "SELECT book_number, title_english, title_translit, author_english, summary_english FROM books"
    ).fetchall()
    for b in b_rows:
        conn.execute(
            "UPDATE books SET title_english = ?, title_translit = ?, author_english = ?, summary_english = ? WHERE book_number = ?",
            (
                clean_human_readable_english(b["title_english"]),
                clean_human_readable_english(b["title_translit"]),
                clean_human_readable_english(b["author_english"]),
                clean_human_readable_english(b["summary_english"]),
                b["book_number"],
            ),
        )

    # Clean chapters
    c_rows = conn.execute("SELECT id, heading_english, keywords FROM chapters").fetchall()
    for c in c_rows:
        conn.execute(
            "UPDATE chapters SET heading_english = ?, keywords = ? WHERE id = ?",
            (
                clean_human_readable_english(c["heading_english"]),
                clean_human_readable_english(c["keywords"]),
                c["id"],
            ),
        )

    # Rebuild FTS tables
    conn.execute("DELETE FROM pages_fts")
    conn.execute(
        """
        INSERT INTO pages_fts (
            page_id, volume_number, book_number, pdf_page, book_page,
            text_urdu, text_english, summary_english, citations
        )
        SELECT id, volume_number, book_number, pdf_page, book_page,
               text_urdu, text_english, summary_english, citations
        FROM pages
        """
    )
    conn.commit()
    conn.close()


def make_header_footer(header_text: str):
    def add_header_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT_REGULAR, 8.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(
            0.65 * inch,
            10.55 * inch,
            header_text,
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

    return add_header_footer


def build_volume_pdf(vol_num: int, output_path: Path) -> None:
    sanitize_database(DB_PATH)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

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
        fontName=FONT_BOLD,
        fontSize=22,
        leading=28,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=10,
    )
    subtitle_style = ParagraphStyle(
        "CoverSub",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=14,
    )
    book_header_style = ParagraphStyle(
        "BookHeader",
        parent=styles["Heading1"],
        fontName=FONT_BOLD,
        fontSize=15,
        leading=20,
        textColor=colors.HexColor("#1A365D"),
        spaceBefore=10,
        spaceAfter=6,
    )
    page_header_style = ParagraphStyle(
        "PageHeader",
        parent=styles["Heading2"],
        fontName=FONT_BOLD,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=8,
        spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "MetaStyle",
        parent=styles["Normal"],
        fontName=FONT_ITALIC,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#4A5568"),
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "PageBody",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
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

    toc_data = [["Book #", "English Title", "Author", "Book Pages", "PDF Pages"]]
    books_by_num = {}
    for b in books:
        books_by_num[b["book_number"]] = b
        toc_data.append(
            [
                f"Book {b['book_number']}",
                Paragraph(escape(clean_human_readable_english(b["title_english"])), body_style),
                Paragraph(escape(clean_human_readable_english(b["author_english"])), body_style),
                f"pp. {b['book_start_page']}-{b['book_end_page']}",
                f"pp. {b['pdf_start_page']}-{b['pdf_end_page']}",
            ]
        )

    t = Table(toc_data, colWidths=[0.7 * inch, 2.9 * inch, 1.9 * inch, 0.85 * inch, 0.85 * inch])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A365D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
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
                    f"Book {b_num}: {escape(clean_human_readable_english(b_info['title_english']))} "
                    f"({escape(clean_human_readable_english(b_info['title_translit']))})",
                    book_header_style,
                )
            )
            story.append(
                Paragraph(
                    f"<b>Author:</b> {escape(clean_human_readable_english(b_info['author_english']))} | "
                    f"<b>Book Pages:</b> {b_info['book_start_page']}-{b_info['book_end_page']} "
                    f"(PDF pp. {b_info['pdf_start_page']}-{b_info['pdf_end_page']})",
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
                    f"<b>Summary:</b> {escape(clean_human_readable_english(p['summary_english']))}",
                    meta_style,
                )
            )
        if p["citations"]:
            story.append(
                Paragraph(
                    f"<b>Citations / Sources:</b> {escape(clean_human_readable_english(p['citations']))}",
                    meta_style,
                )
            )

        text_eng = clean_human_readable_english(p["text_english"] or "")
        for para in text_eng.split("\n"):
            clean_p = para.strip()
            if clean_p:
                story.append(Paragraph(escape(clean_p), body_style))

        story.append(Spacer(1, 0.1 * inch))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0")))

    if books:
        b_range = f"Books {books[0]['book_number']}-{books[-1]['book_number']}" if len(books) > 1 else f"Book {books[0]['book_number']}"
    else:
        b_range = ""
    hf = make_header_footer(f"Majmua Kutub Ihtisab-e-Nasbiyat — Volume {vol_num} Complete English Translation ({b_range})")
    doc.build(story, onFirstPage=hf, onLaterPages=hf)
    print(f"Exported clean human-readable Volume {vol_num} English PDF ({len(pages)} pages) -> {output_path}")


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
