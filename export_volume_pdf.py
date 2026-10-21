#!/usr/bin/env python3
"""
Exports a complete English translation PDF for any volume of Majmua Kutub Ihtisab-e-Nasbiyat
modeled directly on the Al-Islam.org book export layout, typography, cover design, and continuous
reading flow (https://al-islam.org/printpdf/book/export/html/18725).
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "ihtisab_nasbiyat.db"
FLORAL_BG_PATH = BASE_DIR / "data" / "al_islam_floral_bg.jpg"
BADGE_PATH = BASE_DIR / "data" / "al_islam_badge.png"

PAGE_W, PAGE_H = A4  # 595.28 x 841.89 pts (exact Al-Islam.org A4 page size)
MARGIN_LR = 42.5
MARGIN_TB = 48.0

# Register TrueType fonts (Liberation Sans closely matches XBRiyaz metrics & supports full Unicode)
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
    FONT_BOLD_ITALIC = "LibSans-BoldItalic"
else:
    FONT_REGULAR = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"
    FONT_ITALIC = "Helvetica-Oblique"
    FONT_BOLD_ITALIC = "Helvetica-BoldOblique"

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
    nfkd = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    s = re.sub(r"\s*\([\u0600-\u06FF\s]+\)", "", s)
    s = re.sub(r"[\u0600-\u06FF]+", "", s)
    return s.strip()


def sanitize_database(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

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


def is_running_header_or_noise(line: str, book_titles: List[str]) -> bool:
    """Detects OCR running page headers, page numbers, and bracketed scaffolding."""
    s = line.strip()
    if not s:
        return True
    # Bracketed header / page tags
    if re.match(r"^\[(Header|Running Header|Page|Book Page|PDF Page|Top Header|Footer)[^\]]*\]$", s, re.I):
        return True
    # Pipe-separated running header: "Title | 193 | Author" or "Page 218 | Title"
    if "|" in s and len(s) < 160 and re.search(r"\b(Page\s*\d+|\d{1,3})\b", s, re.I):
        # Do not strip TOC lines that start with [Page] 318 | ... unless it's a running header
        if not s.startswith("[Page]"):
            return True
    # Standalone page numbers: "Page 14", "(14)", "[14]", "- 14 -", "14"
    if re.match(r"^(Page\s*)?[\(\[\-\s]*\d{1,4}[\)\]\-\s]*$", s, re.I):
        return True
    # Common running headers at top of pages in Vol 1 & Vol 2
    lower = s.lower()
    running_patterns = [
        "yazid's personality in the view of ibn al-jawzi",
        "the personality of yazid in the view of",
        "personality of yazid in the eyes of",
        "ihya' al-mayyit bi-fada'il ahl al-bayt",
        "uswa-e-husayni",
        "the exemplary character of husayn",
        "martyr of karbala",
        "what are the decisive proofs in the case of yazid",
        "in the case of yazid, what are the decisive",
        "tragedy of karbala",
        "the martyrdom of husayn",
        "life of yazid",
        "refutation of kharijism",
        "fitnat al-kharijiyyah",
        "hadith of the expedition of constantinople",
        "the reality of yazid",
    ]
    if len(s) < 125:
        for pat in running_patterns:
            if pat in lower and not lower.startswith(("chapter", "section", "book", "1.", "2.", "3.")):
                return True
        for bt in book_titles:
            if bt and len(bt) > 12 and bt.lower() in lower:
                return True
    return False


def clean_page_lines(raw_text: str, book_titles: List[str]) -> Tuple[List[str], List[str]]:
    """
    Cleans a single page's raw English translation into body lines and footnotes,
    stripping OCR running headers, page numbers, and markdown wrappers.
    """
    text = clean_human_readable_english(raw_text)
    # Remove "[...continued from the previous page:" wrappers while keeping inner text
    text = re.sub(
        r"\[\.{0,3}\s*continued from (?:the )?previous page:\s*([^\]]+)\]",
        r"\1",
        text,
        flags=re.I,
    )
    text = re.sub(r"^\[(?:Arabic|Urdu|Translation|Main Text|Text)[^\]]*\]:?\s*", "", text, flags=re.I | re.M)

    raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    body_lines: List[str] = []
    footnotes: List[str] = []

    in_footnotes = False
    for idx, ln in enumerate(raw_lines):
        # Strip markdown hashes, bold asterisks, and inline italic asterisks
        ln = re.sub(r"^#{1,6}\s*", "", ln)
        ln = ln.replace("**", "").replace("__", "")
        ln = re.sub(r"\*([^*\n]+)\*", r"'\1'", ln)

        # Check first 3 lines and last 2 lines for running headers / page numbers
        if (idx < 3 or idx >= len(raw_lines) - 2) and is_running_header_or_noise(ln, book_titles):
            continue

        # Check for footnote markers
        if re.match(r"^(\[?Footnote\s*\d*[:\]]|Footnotes?:|\[\d+\]\s+\w)", ln, re.I):
            in_footnotes = True
            clean_fn = re.sub(r"^\[?Footnotes?\s*(\d*)[:\]]?\s*", lambda m: f"{m.group(1) or '1'}. ", ln, flags=re.I)
            footnotes.append(clean_fn.strip("[] "))
            continue

        if in_footnotes and (len(ln) < 220 or re.match(r"^\d+[\.\)]\s+", ln)):
            footnotes.append(ln.strip("[] "))
            continue

        body_lines.append(ln)

    return body_lines, footnotes


def classify_paragraph(para: str) -> str:
    """
    Classifies a paragraph into Al-Islam.org structural styles:
      - 'divider' (* * *)
      - 'bismillah' (In the Name of Allah... / Bismillah...)
      - 'h2' (Section / Chapter Heading -> Bold Blue Underlined)
      - 'h3' (Short Subheading -> Bold Black)
      - 'quote' (Standalone Quranic Verse or Hadith quote -> Bold Italic)
      - 'body' (Standard flowing paragraph)
    """
    s = para.strip()
    if not s:
        return "empty"
    if re.match(r"^[\*\-\s]{3,}$", s):
        return "divider"
    if re.match(
        r"^(Bismillah|In the Name of Allah,\s*the Most Gracious,\s*the Most Merciful\.?)$",
        s,
        re.I,
    ):
        return "bismillah"

    # Never classify TOC lines (with leader dots or trailing page numbers), imprint lines, or signatures as H2
    if (
        "..." in s
        or "|" in s
        or re.search(r"\b(Page|Printer|Publisher|Phone|Edition|Road|Multan|Lahore|Karachi|Authorship|Arrangement| prayers)\b", s, re.I)
        or re.search(r"\s\d{1,4}$", s)
        or s.endswith(":")
    ):
        if len(s) <= 65 and s.endswith(":") and not s.startswith(('"', "'")) and "..." not in s:
            return "h3"
        return "body"

    # Check if it's an explicit section / chapter heading
    if len(s) <= 105 and not s.endswith((".", "!", "?", '"', "'", ";", ",")) and not s.startswith(('"', "'", "-", "*")):
        if re.match(
            r"^(Chapter|Section|Part|Discourse|Premise|Hadith No\.|Argument|Objection|Answer|Reply|Response|Conclusion|Introduction|Preface|Foreword|Translator's Note|Second Note|Introductory Remarks|Additional Remarks|Historical|First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth)\b",
            s,
            re.I,
        ):
            return "h2"

    # Check if it's a standalone Quranic verse or short Hadith quote in quotation marks with citation
    if (
        len(s) <= 420
        and (s.startswith('"') or s.startswith("'"))
        and (
            re.search(r"\((?:Surah|Qur'?an|Ch\.|Chapter|\d+:\d+|Bukhari|Muslim|Tirmidhi|Ahmad|Abu Dawud)", s, re.I)
            or s.endswith(('"', "'"))
        )
        and len(s) >= 40
    ):
        return "quote"

    return "body"


def merge_continuous_blocks(
    page_rows: list,
    chapters_by_page: dict,
    book_titles: List[str],
) -> List[Tuple[str, str]]:
    """
    Transforms page-by-page OCR translations for a book into a continuous stream of
    (block_type, text) tuples, joining sentences that were split across page breaks.
    """
    blocks: List[Tuple[str, str]] = []
    seen_headings = set()

    for r in page_rows:
        p_num = r["pdf_page"]
        # Inject any indexed chapter headings that start on this page if not already emitted
        for ch_heading in chapters_by_page.get(p_num, []):
            norm_h = re.sub(r"\W+", "", ch_heading.lower())
            if norm_h and norm_h not in seen_headings and len(ch_heading) > 3:
                seen_headings.add(norm_h)
                blocks.append(("h2", ch_heading))

        body_lines, footnotes = clean_page_lines(r["text_english"] or "", book_titles)

        for idx, line in enumerate(body_lines):
            # Remove leading ellipsis from page continuation
            is_continuation_ellipsis = bool(re.match(r"^\.{2,}\s*", line))
            clean_line = re.sub(r"^\.{2,}\s*", "", line).strip()
            if not clean_line:
                continue

            btype = classify_paragraph(clean_line)

            # Avoid duplicate consecutive headings
            if btype in ("h2", "h3"):
                norm_h = re.sub(r"\W+", "", clean_line.lower())
                if norm_h in seen_headings:
                    continue
                seen_headings.add(norm_h)

            # If this is the first line of a new page and the previous block is an unfinished body paragraph,
            # merge them into a single seamless paragraph!
            if (
                idx == 0
                and blocks
                and blocks[-1][0] == "body"
                and btype == "body"
                and (
                    is_continuation_ellipsis
                    or not blocks[-1][1].rstrip().endswith((".", "!", "?", ":", '"', "'", ")"))
                    or clean_line[0].islower()
                )
            ):
                prev_text = blocks[-1][1].rstrip()
                if prev_text.endswith("-"):
                    blocks[-1] = ("body", prev_text[:-1] + clean_line)
                else:
                    blocks[-1] = ("body", prev_text + " " + clean_line)
            else:
                blocks.append((btype, clean_line))

        for fn in footnotes:
            blocks.append(("footnote", fn))

    return blocks


def draw_wrapped_centered_lines(
    canvas,
    text: str,
    font_name: str,
    font_size: float,
    leading: float,
    center_x: float,
    start_y: float,
    max_width: float,
    fill_color,
    halo_color=None,
) -> float:
    """Helper to wrap and draw centered text on the ReportLab canvas."""
    words = text.split()
    lines = []
    cur = []
    for w in words:
        test = " ".join(cur + [w])
        if pdfmetrics.stringWidth(test, font_name, font_size) <= max_width or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    canvas.setFont(font_name, font_size)
    y = start_y
    for ln in lines:
        if halo_color is not None:
            canvas.setFillColor(halo_color)
            for dx, dy in [(-1.2, 0), (1.2, 0), (0, -1.2), (0, 1.2), (-0.8, 0.8), (0.8, -0.8)]:
                canvas.drawCentredString(center_x + dx, y + dy, ln)
        canvas.setFillColor(fill_color)
        canvas.drawCentredString(center_x, y, ln)
        y -= leading
    return y


def make_page_decorator(vol_num: int, vol_title: str, authors_str: str, translators_str: str, medallion_img: Optional[Path]):
    """
    Draws Page 2 using the original volume cover image from the PDF as a full cover picture
    (with no Al-Islam.org floral background or badge), and leaves all other pages with clean white margins.
    """

    def on_page(canvas, doc):
        if doc.page != 2:
            return

        canvas.saveState()
        box_x = MARGIN_LR
        box_y = MARGIN_TB
        box_w = PAGE_W - 2 * MARGIN_LR
        box_h = PAGE_H - 2 * MARGIN_TB

        if medallion_img and medallion_img.exists():
            canvas.drawImage(
                str(medallion_img),
                box_x,
                box_y,
                width=box_w,
                height=box_h,
                preserveAspectRatio=True,
                anchor="c",
            )
        else:
            canvas.setStrokeColor(colors.HexColor("#888888"))
            canvas.setLineWidth(0.8)
            canvas.rect(box_x, box_y, box_w, box_h, fill=0, stroke=1)

        canvas.restoreState()

    return on_page


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
    chapters = conn.execute(
        "SELECT * FROM chapters WHERE volume_number = ? ORDER BY pdf_page, id", (vol_num,)
    ).fetchall()
    conn.close()

    chapters_by_page = {}
    for c in chapters:
        chapters_by_page.setdefault(c["pdf_page"], []).append(
            clean_human_readable_english(c["heading_english"])
        )

    book_titles = [clean_human_readable_english(b["title_english"]) for b in books]
    unique_authors = []
    for b in books:
        a_clean = re.sub(r"\s*\([^)]*\)", "", clean_human_readable_english(b["author_english"])).strip()
        if a_clean and a_clean not in unique_authors:
            unique_authors.append(a_clean)

    vol_title = f"Ihtisab-e-Nasbiyat — Volume {vol_num}"
    if len(unique_authors) <= 2:
        cover_authors_str = " & ".join(unique_authors)
    else:
        cover_authors_str = ", ".join(unique_authors[:3]) + f" & {len(unique_authors) - 3} Other Scholars"

    translators_str = "Mufti Muhammad Shuaib Ahmad, Prof. Anwarul Hasan Sherkoti & Digital Edition Team"
    medallion_img = BASE_DIR / "data" / "rendered_pages" / f"vol_{vol_num:02d}" / f"vol{vol_num:02d}_pdf0001_book-001.jpg"
    if not medallion_img.exists():
        medallion_img = BASE_DIR / "data" / "rendered_pages" / f"vol_{vol_num:02d}" / f"vol{vol_num:02d}_pdf0001_book0000.jpg"

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=MARGIN_LR,
        rightMargin=MARGIN_LR,
        topMargin=MARGIN_TB,
        bottomMargin=MARGIN_TB,
        title=vol_title,
        author=cover_authors_str,
        creator="Ihtisab-e-Nasbiyat Digital Library",
    )

    styles = getSampleStyleSheet()

    # Exact Al-Islam.org (18725) Typography Styles
    half_title_style = ParagraphStyle(
        "HalfTitle",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=19,
        leading=24,
        textColor=colors.black,
    )
    meta_heading_style = ParagraphStyle(
        "MetaHeading",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=12.5,
        leading=17,
        textColor=colors.black,
        spaceBefore=12,
        spaceAfter=6,
    )
    meta_link_style = ParagraphStyle(
        "MetaLink",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
        fontSize=10.2,
        leading=15.5,
        leftIndent=6,
        textColor=colors.black,
        spaceAfter=2,
    )
    notice_heading_style = ParagraphStyle(
        "NoticeHeading",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=10.2,
        leading=15.5,
        textColor=colors.black,
        spaceBefore=12,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "AlIslamBody",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
        fontSize=10.2,
        leading=16.2,
        textColor=colors.HexColor("#111111"),
        spaceAfter=9.5,
    )
    h1_style = ParagraphStyle(
        "AlIslamH1",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=18.5,
        leading=25,
        textColor=colors.black,
        spaceBefore=16,
        spaceAfter=12,
        keepWithNext=True,
    )
    h2_blue_style = ParagraphStyle(
        "AlIslamH2Blue",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=14.5,
        leading=21,
        textColor=colors.HexColor("#0000EE"),
        spaceBefore=15,
        spaceAfter=8,
        keepWithNext=True,
    )
    h3_style = ParagraphStyle(
        "AlIslamH3",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=10.5,
        leading=16,
        textColor=colors.black,
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True,
    )
    quote_style = ParagraphStyle(
        "AlIslamQuote",
        parent=styles["Normal"],
        fontName=FONT_BOLD_ITALIC,
        fontSize=10.2,
        leading=16.2,
        textColor=colors.black,
        spaceBefore=4,
        spaceAfter=10,
    )
    divider_style = ParagraphStyle(
        "AlIslamDivider",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
        fontSize=10.2,
        leading=16.2,
        textColor=colors.black,
        spaceBefore=6,
        spaceAfter=10,
    )
    footnote_style = ParagraphStyle(
        "AlIslamFootnote",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
        fontSize=8.6,
        leading=13,
        leftIndent=22,
        textColor=colors.HexColor("#222222"),
        spaceAfter=3,
    )

    story = []
    links_registry: List[Tuple[int, str]] = []

    def register_link(url_str: str) -> int:
        idx = len(links_registry) + 1
        links_registry.append((idx, url_str))
        return idx

    # =========================================================================
    # PAGE 1: Half-Title Page (Matches page-001.jpg of 18725)
    # =========================================================================
    story.append(Paragraph(escape(vol_title), half_title_style))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 2: Full Floral Cover Page (Drawn by on_page canvas callback)
    # =========================================================================
    story.append(Spacer(1, 10))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 3: Metadata, Links, Topic Tags & Editorial Notice (Matches page-003.jpg)
    # =========================================================================
    story.append(Paragraph("Author(s):", meta_heading_style))
    for auth in unique_authors:
        slug = re.sub(r"[^a-z0-9]+", "-", auth.lower()).strip("-")
        l_idx = register_link(f"https://ihtisab-nasbiyat-mcp.onrender.com/person/{slug}")
        story.append(
            Paragraph(
                f'<u><font color="#0000EE">{escape(auth)}</font></u> [{l_idx}]',
                meta_link_style,
            )
        )

    story.append(Paragraph("Publisher(s):", meta_heading_style))
    pub_idx = register_link("https://ihtisab-nasbiyat-mcp.onrender.com/organization/maktabah-sirajiyyah-multan")
    story.append(
        Paragraph(
            f'<u><font color="#0000EE">Maktabah Sirajiyyah / Maktabah Ihya\' al-Sunnah – Multan</font></u> [{pub_idx}]',
            meta_link_style,
        )
    )
    story.append(Spacer(1, 8))

    b_range_desc = (
        f"Books {books[0]['book_number']} to {books[-1]['book_number']}"
        if len(books) > 1
        else f"Book {books[0]['book_number']}"
    )
    synopsis_text = (
        f"Complete English translation of Volume {vol_num} ({b_range_desc}) of Majmu'a Kutub Ihtisab-e-Nasbiyat, "
        f"comprising {len(books)} classical and contemporary Sunni scholarly treatises examining the virtues of the "
        f"Ahl al-Bayt, the martyrdom of Imam Husayn at Karbala, historical criticism of the reign of Yazid ibn "
        f"Mu'awiyah, and the refutation of Nasibi and Khariji deviations. Includes full-text search via MCP."
    )
    story.append(Paragraph(escape(synopsis_text), body_style))

    pdf_idx = register_link(f"https://ihtisab-nasbiyat-mcp.onrender.com/printpdf/volume/{vol_num}")
    epub_idx = register_link(f"https://ihtisab-nasbiyat-mcp.onrender.com/printepub/volume/{vol_num}")
    mobi_idx = register_link(f"https://ihtisab-nasbiyat-mcp.onrender.com/printmobi/volume/{vol_num}")
    story.append(
        Paragraph(
            f'<u><font color="#0000EE">Get PDF</font></u> [{pdf_idx}] '
            f'<u><font color="#0000EE">Get EPUB</font></u> [{epub_idx}] '
            f'<u><font color="#0000EE">Get MOBI</font></u> [{mobi_idx}]',
            body_style,
        )
    )

    story.append(Paragraph("Translator(s):", meta_heading_style))
    for tr_name in [
        "Mufti Muhammad Shuaib Ahmad",
        "Prof. Maulana Anwarul Hasan Sherkoti",
        "Ihtisab-e-Nasbiyat Digital Translation Team",
    ]:
        slug = re.sub(r"[^a-z0-9]+", "-", tr_name.lower()).strip("-")
        t_idx = register_link(f"https://ihtisab-nasbiyat-mcp.onrender.com/translator/{slug}")
        story.append(
            Paragraph(
                f'<u><font color="#0000EE">{escape(tr_name)}</font></u> [{t_idx}]',
                meta_link_style,
            )
        )

    story.append(Paragraph("Topic Tags:", meta_heading_style))
    for tag_name, tag_slug in [
        ("Ahl al-Bayt & Companions", "ahl-al-bayt-and-companions"),
        ("Refutation of Nasbism (Ihtisab-e-Nasbiyat)", "refutation-of-nasbism"),
        ("Karbala & Historical Criticism", "karbala-and-historical-criticism"),
    ]:
        tg_idx = register_link(f"https://ihtisab-nasbiyat-mcp.onrender.com/tags/{tag_slug}")
        story.append(
            Paragraph(
                f'<u><font color="#0000EE">{escape(tag_name)}</font></u> [{tg_idx}]',
                meta_link_style,
            )
        )

    story.append(Paragraph("Important notice:", notice_heading_style))
    notice_body = (
        "The Digital Translation Team wishes to inform the reader of some important points regarding this digitized "
        "text, which represents the complete English translation of a work originally compiled in Urdu and classical "
        "Arabic. In making this multi-volume scholarly compendium accessible to an English-speaking audience, the "
        "editing and digitization process has prioritized fluent, continuous readability alongside rigorous fidelity "
        "to the primary Hadith, historical, and biographical (Rijal) citations. Running page headers from the scanned "
        "print edition have been removed so the prose flows seamlessly across pages, and Arabic and Urdu names and "
        "book titles have been standardized into clear, human-readable English transliteration without complex "
        "diacritical marks. Readers wishing to inspect the original Urdu typography may consult the scanned volumes "
        "directly."
    )
    story.append(Paragraph(escape(notice_body), body_style))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 4+: Continuous Book Content (Matches page-004.jpg .. p15-016.jpg)
    # =========================================================================
    story.append(Paragraph("Translators' Preface & Volume Overview", h1_style))
    story.append(
        Paragraph(
            escape(
                f"This volume presents the complete English translation of Volume {vol_num} of Majmu'a Kutub "
                f"Ihtisab-e-Nasbiyat, containing {len(books)} foundational treatises authored by classical and "
                f"contemporary Sunni authorities. We have followed a middle course in the transliteration of "
                f"Arabic and Urdu terms, avoiding specialized diacritical symbols that would be daunting to the "
                f"general reader while preserving every classical reference, chain of transmission (isnad), and "
                f"bibliographic citation in full."
            ),
            body_style,
        )
    )
    story.append(Paragraph("* * *", divider_style))

    for b in books:
        b_title = clean_human_readable_english(b["title_english"])
        b_translit = clean_human_readable_english(b["title_translit"])
        b_author = clean_human_readable_english(b["author_english"])
        b_summary = clean_human_readable_english(b["summary_english"])
        story.append(
            Paragraph(
                f'<u><font color="#0000EE">Book {b["book_number"]}: {escape(b_title)}</font></u>',
                h2_blue_style,
            )
        )
        story.append(
            Paragraph(
                f"<b>Original Title:</b> {escape(b_translit)} | <b>Author:</b> {escape(b_author)}",
                body_style,
            )
        )
        story.append(Paragraph(escape(b_summary), body_style))

    story.append(PageBreak())

    # Group pages by book_number (front matter prose pages before Book 1/10 go into an introductory section)
    pages_by_book = {}
    front_matter_pages = []
    for p in pages:
        b_num = p["book_number"]
        if b_num:
            pages_by_book.setdefault(b_num, []).append(p)
        elif (p["book_page"] or 0) >= 4 and p["pdf_page"] < (books[0]["pdf_start_page"] if books else 9999):
            front_matter_pages.append(p)

    if front_matter_pages:
        story.append(Paragraph("Publisher's Preface (Arz-e-Nashir)", h1_style))
        story.append(Paragraph("Bismillah Ar-Rahman Ar-Rahim", h3_style))
        fm_blocks = merge_continuous_blocks(front_matter_pages, chapters_by_page, book_titles)
        pending_footnotes = []
        for btype, text in fm_blocks:
            if btype == "footnote":
                pending_footnotes.append(text)
            elif btype == "divider":
                story.append(Paragraph("* * *", divider_style))
            elif btype == "bismillah":
                story.append(Paragraph(escape(text), h3_style))
            elif btype == "h2":
                story.append(
                    Paragraph(f'<u><font color="#0000EE">{escape(text)}</font></u>', h2_blue_style)
                )
            elif btype == "h3":
                story.append(Paragraph(escape(text), h3_style))
            elif btype == "quote":
                story.append(Paragraph(escape(text), quote_style))
            else:
                story.append(Paragraph(escape(text), body_style))
        if pending_footnotes:
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="35%", thickness=0.5, color=colors.HexColor("#888888"), hAlign="LEFT"))
            for idx_fn, fn in enumerate(pending_footnotes, 1):
                story.append(Paragraph(escape(f"{idx_fn}. {fn}"), footnote_style))
        story.append(PageBreak())

    # Emit each treatise (Book) as a continuous narrative matching 18725
    for idx_b, b in enumerate(books):
        b_num = b["book_number"]
        b_pages = pages_by_book.get(b_num, [])
        if not b_pages:
            continue

        # Skip initial sub-cover / inner-title stub pages that have very little text (< 450 chars)
        while len(b_pages) > 1 and len((b_pages[0]["text_english"] or "").strip()) < 450:
            b_pages = b_pages[1:]

        b_title = clean_human_readable_english(b["title_english"])
        b_author = clean_human_readable_english(b["author_english"])

        story.append(Paragraph(escape(b_title), h1_style))
        story.append(Paragraph(escape(f"By {b_author}"), h3_style))
        story.append(Paragraph("Bismillah Ar-Rahman Ar-Rahim", h3_style))

        blocks = merge_continuous_blocks(b_pages, chapters_by_page, book_titles)
        pending_footnotes: List[str] = []

        for btype, text in blocks:
            if btype == "footnote":
                pending_footnotes.append(text)
                continue

            # Flush footnotes before a new major section heading (just like page-008.jpg of 18725)
            if btype == "h2" and pending_footnotes:
                story.append(Spacer(1, 4))
                story.append(
                    HRFlowable(width="32%", thickness=0.5, color=colors.HexColor("#666666"), hAlign="LEFT")
                )
                story.append(Spacer(1, 3))
                for fn_i, fn_txt in enumerate(pending_footnotes, 1):
                    clean_fn = re.sub(r"^\d+[\.\)]\s*", "", fn_txt)
                    story.append(
                        Paragraph(
                            f'<u><font color="#0000EE">{fn_i}.</font></u> {escape(clean_fn)}',
                            footnote_style,
                        )
                    )
                story.append(Spacer(1, 8))
                pending_footnotes.clear()

            if btype == "divider":
                story.append(Paragraph("* * *", divider_style))
            elif btype == "bismillah":
                story.append(Paragraph(escape(text), h3_style))
            elif btype == "h2":
                story.append(
                    Paragraph(f'<u><font color="#0000EE">{escape(text)}</font></u>', h2_blue_style)
                )
            elif btype == "h3":
                story.append(Paragraph(escape(text), h3_style))
            elif btype == "quote":
                story.append(Paragraph(escape(text), quote_style))
            else:
                story.append(Paragraph(escape(text), body_style))

        if pending_footnotes:
            story.append(Spacer(1, 4))
            story.append(
                HRFlowable(width="32%", thickness=0.5, color=colors.HexColor("#666666"), hAlign="LEFT")
            )
            story.append(Spacer(1, 3))
            for fn_i, fn_txt in enumerate(pending_footnotes, 1):
                clean_fn = re.sub(r"^\d+[\.\)]\s*", "", fn_txt)
                story.append(
                    Paragraph(
                        f'<u><font color="#0000EE">{fn_i}.</font></u> {escape(clean_fn)}',
                        footnote_style,
                    )
                )
            pending_footnotes.clear()

        if idx_b < len(books) - 1:
            story.append(PageBreak())

    # =========================================================================
    # FINAL PAGE: Source URL & Links (Matches p444-445.jpg of 18725)
    # =========================================================================
    story.append(PageBreak())
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#888888")))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Source URL:</b>", body_style))
    story.append(
        Paragraph(
            escape(f"https://ihtisab-nasbiyat-mcp.onrender.com/volume-{vol_num}"),
            body_style,
        )
    )
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Links</b>", body_style))
    for l_idx, l_url in links_registry:
        story.append(
            Paragraph(
                escape(f"[{l_idx}] {l_url}"),
                ParagraphStyle(
                    "LinkItem",
                    parent=body_style,
                    fontSize=9.5,
                    leading=14.5,
                    spaceAfter=2,
                ),
            )
        )

    on_page_cb = make_page_decorator(vol_num, vol_title, cover_authors_str, translators_str, medallion_img)
    doc.build(story, onFirstPage=on_page_cb, onLaterPages=on_page_cb)
    print(f"Exported Al-Islam.org style Volume {vol_num} PDF ({len(pages)} source pages) -> {output_path}")


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
