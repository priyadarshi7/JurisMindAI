"""HTML filing parser / cleaner (docs/04 Stage 3).

Turns a raw SEC filing (HTML) into structured text: section-delimited body
text plus separately-extracted tables, ready for section-aware chunking
(docs/04 Stage 6, D-19).

❗ This module does NOT sanitize against prompt injection. "Treat all
source content as untrusted data" (docs/04, docs/12 §12) is enforced at the
LLM prompt boundary — every prompt in `src/prompts/` already instructs the
model to ignore instruction-like content inside retrieved passages. No
regex filter here can reliably strip an injection attempt without also
corrupting legitimate filing text (a 10-K routinely contains phrases like
"ignore the effect of..." in ordinary financial prose). Treating this
parser as a security boundary would be a false sense of safety.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

# Many real EDGAR filings are "inline XBRL" — HTML with XBRL namespace
# declarations up top. bs4 warns that an XML parser would be more reliable;
# in practice the lxml HTML parser handles these filings fine (verified
# against a live NVIDIA 10-K in tests/integration/test_parser_real_filing.py)
# and switching to strict XML parsing would break on filings that mix real
# HTML markup errors XML parsers refuse to tolerate.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Matches SEC filing section headers: "Item 1A.", "ITEM 7.", "Item 7A. ",
# optionally followed by a title on the same line/node.
_ITEM_HEADER_PATTERN = re.compile(r"^\s*item\s+(\d{1,2}[a-z]?)\.?\s*[-—:]?\s*(.*)$", re.IGNORECASE)
_MAX_HEADER_TEXT_LENGTH = 120  # a real "Item 7." heading is short; a hit
# this long is almost certainly a paragraph that happens to start similarly.


@dataclass(frozen=True)
class ExtractedTable:
    """A `<table>` pulled out of the flow, table-aware per D-19 — never
    flattened into the surrounding paragraph text.
    """

    title: str | None
    headers: list[str]
    rows: list[list[str]]
    section: str | None


@dataclass(frozen=True)
class DocumentSection:
    name: str
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    sections: list[DocumentSection] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(s.text for s in self.sections if s.text.strip())


class ParseError(Exception):
    pass


def parse_filing_html(raw_html: bytes) -> ParsedDocument:
    """Parse one filing document into sections + tables.

    Heuristic, not a certified SEC-filing parser: splits on "Item N." /
    "Item NA." headers, which covers 10-K/10-Q/8-K structure well but is
    not guaranteed to catch every filer's formatting quirk. Falls back to a
    single "document" section when no Item headers are found (e.g. an 8-K
    exhibit, an investor presentation) rather than failing.
    """
    try:
        soup = BeautifulSoup(raw_html, "lxml")
    except Exception as exc:
        raise ParseError(f"failed to parse HTML: {exc}") from exc

    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: s.__class__.__name__ == "Comment"):
        comment.extract()

    tables = _extract_tables(soup)
    # Tables are pulled out of the tree before block-text extraction so
    # their (often dense, poorly-linearized) cell text doesn't pollute the
    # surrounding section's prose.
    for table_tag in soup.find_all("table"):
        table_tag.decompose()

    sections = _extract_sections(soup)
    # ExtractedTable.section is left None: precisely re-associating a table
    # with its originating section would require tracking position through
    # the tree before tables were pulled out above, which this pass does
    # not do. Left unknown rather than guessed.

    return ParsedDocument(sections=sections, tables=tables)


def _extract_tables(soup: BeautifulSoup) -> list[ExtractedTable]:
    extracted: list[ExtractedTable] = []
    for table_tag in soup.find_all("table"):
        rows: list[list[str]] = []
        for row_tag in table_tag.find_all("tr"):
            cells = [
                _clean_text(cell.get_text(" ", strip=True))
                for cell in row_tag.find_all(["td", "th"])
            ]
            if any(cell for cell in cells):
                rows.append(cells)

        if not rows:
            continue

        headers = rows[0] if _looks_like_header_row(table_tag) else []
        data_rows = rows[1:] if headers else rows
        title = _find_preceding_caption(table_tag)

        extracted.append(ExtractedTable(title=title, headers=headers, rows=data_rows, section=None))
    return extracted


def _looks_like_header_row(table_tag: Tag) -> bool:
    first_row_tag = table_tag.find("tr")
    return first_row_tag is not None and first_row_tag.find("th") is not None


def _find_preceding_caption(table_tag: Tag) -> str | None:
    caption = table_tag.find("caption")
    if caption is not None:
        text = _clean_text(caption.get_text(" ", strip=True))
        return text or None

    previous = table_tag.find_previous(["p", "div", "span"])
    if previous is not None:
        text = _clean_text(previous.get_text(" ", strip=True))
        if text and len(text) < _MAX_HEADER_TEXT_LENGTH:
            return text
    return None


def _extract_sections(soup: BeautifulSoup) -> list[DocumentSection]:
    body = soup.body or soup
    blocks = [
        _clean_text(el.get_text(" ", strip=True))
        for el in body.find_all(["p", "div", "span", "h1", "h2", "h3", "h4", "li"])
    ]
    blocks = [b for b in blocks if b]

    sections: list[DocumentSection] = []
    current_name = "document"
    current_lines: list[str] = []

    for block in blocks:
        header_match = (
            _ITEM_HEADER_PATTERN.match(block) if len(block) < _MAX_HEADER_TEXT_LENGTH else None
        )
        if header_match:
            if current_lines:
                sections.append(DocumentSection(name=current_name, text="\n".join(current_lines)))
            item_number, title = header_match.groups()
            current_name = f"Item {item_number.upper()}" + (f" {title}" if title else "")
            current_lines = []
        else:
            current_lines.append(block)

    if current_lines:
        sections.append(DocumentSection(name=current_name, text="\n".join(current_lines)))

    if not sections:
        sections = [DocumentSection(name="document", text="")]

    return sections


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
