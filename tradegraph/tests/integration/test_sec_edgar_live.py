"""Integration test: real calls against the live SEC EDGAR API.

No docker-compose service needed here — "integration" in this repo also
covers live external network dependencies (pyproject.toml marker
description), and SEC EDGAR is exactly that: a real service this adapter
must work against, not something to mock forever.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from src.rag.ingestion.sec_edgar import SecEdgarClient


@pytest.fixture
def client() -> SecEdgarClient:
    return SecEdgarClient(user_agent="TradeGraph-Test research@example.com")


def test_resolve_nvda_cik(client: SecEdgarClient) -> None:
    try:
        cik = client.get_cik_for_ticker("NVDA")
    except httpx.HTTPError as exc:
        pytest.skip(f"SEC EDGAR unreachable: {exc}")
    assert cik == "0001045810"


def test_list_recent_nvda_filings(client: SecEdgarClient) -> None:
    try:
        filings = client.list_filings("NVDA", since=date(2023, 1, 1))
    except httpx.HTTPError as exc:
        pytest.skip(f"SEC EDGAR unreachable: {exc}")

    assert len(filings) > 0
    assert all(f.form in {"10-K", "10-Q", "8-K"} for f in filings)
    assert all(f.ticker == "NVDA" for f in filings)
    # NVIDIA has filed at least one 10-K since 2023 — a real content check,
    # not just "the call didn't throw."
    assert any(f.form == "10-K" for f in filings)


def test_fetch_one_real_filing_document(client: SecEdgarClient) -> None:
    try:
        filings = client.list_filings("NVDA", forms=frozenset({"10-K"}))
    except httpx.HTTPError as exc:
        pytest.skip(f"SEC EDGAR unreachable: {exc}")

    assert filings, "expected at least one 10-K in NVDA's recent filings"
    latest = max(filings, key=lambda f: f.filing_date)

    body = client.fetch_filing_document(latest.document_url)
    assert len(body) > 1000  # a real 10-K is large; a stub/error page would not be
    assert b"NVIDIA" in body or b"nvidia" in body.lower()
