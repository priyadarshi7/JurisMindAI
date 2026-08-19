"""Integration test: run the parser against a real, current NVIDIA 10-K
fetched live from SEC EDGAR — synthetic fixtures can't validate that this
parser survives the actual mess of a real filer's HTML.
"""

from __future__ import annotations

import httpx
import pytest

from src.rag.ingestion.parser import parse_filing_html
from src.rag.ingestion.sec_edgar import SecEdgarClient


@pytest.fixture(scope="module")
def real_10k_html() -> bytes:
    try:
        with SecEdgarClient(user_agent="TradeGraph-Test research@example.com") as client:
            filings = client.list_filings("NVDA", forms=frozenset({"10-K"}))
            if not filings:
                pytest.skip("no NVDA 10-K found")
            latest = max(filings, key=lambda f: f.filing_date)
            return client.fetch_filing_document(latest.document_url)
    except httpx.HTTPError as exc:
        pytest.skip(f"SEC EDGAR unreachable: {exc}")


def test_parses_without_raising(real_10k_html: bytes) -> None:
    parsed = parse_filing_html(real_10k_html)
    assert parsed.sections


def test_finds_multiple_item_sections(real_10k_html: bytes) -> None:
    parsed = parse_filing_html(real_10k_html)
    section_names = [s.name for s in parsed.sections]
    # A real 10-K has well over a dozen Item sections; this is a floor,
    # not an exact count, since the heuristic will miss some formatting.
    item_sections = [n for n in section_names if n.lower().startswith("item")]
    assert len(item_sections) >= 5, f"only found sections: {section_names[:20]}"


def test_extracts_a_meaningful_number_of_tables(real_10k_html: bytes) -> None:
    parsed = parse_filing_html(real_10k_html)
    # A 10-K is dense with tables (financial statements, segment data).
    assert len(parsed.tables) >= 5


def test_full_text_is_substantial_and_script_free(real_10k_html: bytes) -> None:
    parsed = parse_filing_html(real_10k_html)
    assert len(parsed.full_text) > 5000
    assert "function(" not in parsed.full_text
    assert "<script" not in parsed.full_text
