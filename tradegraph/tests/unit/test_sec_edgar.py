"""Unit tests for src.rag.ingestion.sec_edgar — HTTP mocked via respx, no
real network calls. Live-API behaviour is covered separately in
tests/integration/test_sec_edgar_live.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import httpx
import pytest
import respx

from src.models.orm import DocumentType
from src.rag.ingestion.sec_edgar import (
    DEFAULT_BENCHMARK_TICKERS,
    SecEdgarClient,
    SecEdgarError,
)

TICKERS_PAYLOAD = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}

SUBMISSIONS_PAYLOAD = {
    "name": "NVIDIA CORP",
    "tickers": ["NVDA"],
    "filings": {
        "recent": {
            "form": ["10-K", "4", "10-Q", "8-K", "SCHEDULE 13G"],
            "filingDate": [
                "2025-02-26",
                "2025-02-20",
                "2024-11-20",
                "2024-08-28",
                "2024-01-01",
            ],
            "reportDate": ["2025-01-26", "", "2024-10-27", "", ""],
            "accessionNumber": [
                "0001045810-25-000023",
                "0001045810-25-000010",
                "0001045810-24-000123",
                "0001045810-24-000098",
                "0001045810-24-000001",
            ],
            "primaryDocument": [
                "nvda-20250126.htm",
                "wk-form4.xml",
                "nvda-20241027.htm",
                "nvda-20240828.htm",
                "primary_doc.xml",
            ],
        }
    },
}


@pytest.fixture
def client() -> Iterator[SecEdgarClient]:
    with SecEdgarClient(
        user_agent="TradeGraph test@example.com", min_request_interval_seconds=0.0
    ) as c:
        yield c


def test_rejects_user_agent_without_contact() -> None:
    with pytest.raises(SecEdgarError, match="User-Agent"):
        SecEdgarClient(user_agent="TradeGraph")


@respx.mock
def test_get_cik_for_ticker(client: SecEdgarClient) -> None:
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=TICKERS_PAYLOAD)
    )
    assert client.get_cik_for_ticker("nvda") == "0001045810"


@respx.mock
def test_get_cik_for_unknown_ticker_raises(client: SecEdgarClient) -> None:
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=TICKERS_PAYLOAD)
    )
    with pytest.raises(SecEdgarError, match="no CIK found"):
        client.get_cik_for_ticker("NOTREAL")


@respx.mock
def test_list_filings_filters_to_10k_10q_8k(client: SecEdgarClient) -> None:
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=TICKERS_PAYLOAD)
    )
    respx.get("https://data.sec.gov/submissions/CIK0001045810.json").mock(
        return_value=httpx.Response(200, json=SUBMISSIONS_PAYLOAD)
    )

    filings = client.list_filings("NVDA")

    forms_found = {f.form for f in filings}
    assert forms_found == {"10-K", "10-Q", "8-K"}
    assert all(
        f.document_type in {DocumentType.FORM_10K, DocumentType.FORM_10Q, DocumentType.FORM_8K}
        for f in filings
    )


@respx.mock
def test_list_filings_since_date_filter(client: SecEdgarClient) -> None:
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=TICKERS_PAYLOAD)
    )
    respx.get("https://data.sec.gov/submissions/CIK0001045810.json").mock(
        return_value=httpx.Response(200, json=SUBMISSIONS_PAYLOAD)
    )

    filings = client.list_filings("NVDA", since=date(2024, 9, 1))

    assert all(f.filing_date >= date(2024, 9, 1) for f in filings)
    assert len(filings) == 2  # the 2025-02-26 10-K and the 2024-11-20 10-Q


@respx.mock
def test_filing_metadata_document_url_construction(client: SecEdgarClient) -> None:
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=TICKERS_PAYLOAD)
    )
    respx.get("https://data.sec.gov/submissions/CIK0001045810.json").mock(
        return_value=httpx.Response(200, json=SUBMISSIONS_PAYLOAD)
    )

    filings = client.list_filings("NVDA", forms=frozenset({"10-K"}))
    assert len(filings) == 1
    filing = filings[0]

    assert filing.document_url == (
        "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm"
    )


@respx.mock
def test_fetch_filing_document_returns_raw_bytes(client: SecEdgarClient) -> None:
    respx.get("https://www.sec.gov/example/filing.htm").mock(
        return_value=httpx.Response(200, content=b"<html>raw filing</html>")
    )
    body = client.fetch_filing_document("https://www.sec.gov/example/filing.htm")
    assert body == b"<html>raw filing</html>"


def test_default_benchmark_tickers_match_d18() -> None:
    """docs/15 D-18 — resolved to exactly these 10 tickers."""
    assert DEFAULT_BENCHMARK_TICKERS == (
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "TSLA",
        "JPM",
        "V",
        "WMT",
    )
