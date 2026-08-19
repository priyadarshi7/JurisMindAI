"""Unit tests for src.rag.ingestion.parser against synthetic filing HTML."""

from __future__ import annotations

from src.rag.ingestion.parser import parse_filing_html

SAMPLE_FILING_HTML = b"""
<html>
<head><style>.x{color:red}</style><script>var x=1;</script></head>
<body>
<div>Item 1A. Risk Factors</div>
<p>Our business is subject to numerous risks, including competition.</p>
<p>Demand for our products may fluctuate.</p>
<div>Item 7. Management's Discussion and Analysis</div>
<p>Gross margin declined due to increased cost of revenue.</p>
<table>
  <caption>Revenue by segment (in millions)</caption>
  <tr><th>Segment</th><th>FY2025</th><th>FY2024</th></tr>
  <tr><td>Data Center</td><td>115,186</td><td>47,525</td></tr>
  <tr><td>Gaming</td><td>11,350</td><td>10,447</td></tr>
</table>
<p>The following table summarizes our revenue by reportable segment.</p>
<div>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</div>
<p>We are exposed to market risk from changes in interest rates.</p>
</body>
</html>
"""

NO_SECTIONS_HTML = b"""
<html><body>
<p>This is an 8-K exhibit with no Item headers, just prose.</p>
<p>Second paragraph of the exhibit.</p>
</body></html>
"""


def test_strips_script_and_style() -> None:
    parsed = parse_filing_html(SAMPLE_FILING_HTML)
    assert "color:red" not in parsed.full_text
    assert "var x=1" not in parsed.full_text


def test_splits_into_item_sections() -> None:
    parsed = parse_filing_html(SAMPLE_FILING_HTML)
    section_names = [s.name for s in parsed.sections]

    assert any(name.startswith("Item 1A") for name in section_names)
    assert any(name.startswith("Item 7 ") or name == "Item 7" for name in section_names)
    assert any(name.startswith("Item 7A") for name in section_names)


def test_section_text_contains_expected_content() -> None:
    parsed = parse_filing_html(SAMPLE_FILING_HTML)
    risk_section = next(s for s in parsed.sections if s.name.startswith("Item 1A"))
    assert "competition" in risk_section.text
    assert "fluctuate" in risk_section.text

    mdna_section = next(
        s for s in parsed.sections if s.name.startswith("Item 7") and "7A" not in s.name
    )
    assert "Gross margin declined" in mdna_section.text


def test_table_extracted_separately_not_flattened_into_prose() -> None:
    parsed = parse_filing_html(SAMPLE_FILING_HTML)

    assert len(parsed.tables) == 1
    table = parsed.tables[0]
    assert table.headers == ["Segment", "FY2025", "FY2024"]
    assert ["Data Center", "115,186", "47,525"] in table.rows
    assert ["Gaming", "11,350", "10,447"] in table.rows

    # The raw numbers must not also be smeared into the surrounding
    # section's linear text — that is exactly the "naively chunked table"
    # failure mode D-19 exists to prevent.
    assert "115,186" not in parsed.full_text


def test_table_caption_captured_as_title() -> None:
    parsed = parse_filing_html(SAMPLE_FILING_HTML)
    assert parsed.tables[0].title == "Revenue by segment (in millions)"


def test_no_item_headers_falls_back_to_single_document_section() -> None:
    parsed = parse_filing_html(NO_SECTIONS_HTML)
    assert len(parsed.sections) == 1
    assert parsed.sections[0].name == "document"
    assert "exhibit" in parsed.sections[0].text


def test_empty_html_does_not_raise() -> None:
    parsed = parse_filing_html(b"<html><body></body></html>")
    assert parsed.full_text == "" or parsed.sections[0].text == ""
