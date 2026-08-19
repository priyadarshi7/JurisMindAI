"""SEC EDGAR adapter (docs/03, docs/16 Phase 1) — the primary authoritative
corpus source for V1.

Talks to SEC's public JSON APIs directly (`data.sec.gov`, `www.sec.gov`) —
no API key, but SEC's fair-access policy requires every request to carry an
identifying `User-Agent` (name + contact) and asks clients to stay under
~10 requests/second. Both are enforced here, not left to the caller.

Only the three document types docs/03 assigns to V1 are surfaced:
10-K, 10-Q, 8-K. Everything else in a company's filing history (Forms 3/4,
Schedule 13G, etc.) is filtered out before it ever becomes a `FilingMetadata`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from threading import Lock

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.models.orm import DocumentType

SEC_FORM_TO_DOCUMENT_TYPE: dict[str, DocumentType] = {
    "10-K": DocumentType.FORM_10K,
    "10-K/A": DocumentType.FORM_10K,
    "10-Q": DocumentType.FORM_10Q,
    "10-Q/A": DocumentType.FORM_10Q,
    "8-K": DocumentType.FORM_8K,
    "8-K/A": DocumentType.FORM_8K,
}

_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


class SecEdgarError(Exception):
    """Raised on a malformed response or an unresolvable ticker — never
    silently returns an empty result for what looks like a real failure.
    """


@dataclass(frozen=True)
class FilingMetadata:
    """One filing, filtered down to what docs/03's metadata schema needs."""

    cik: str
    company_name: str
    ticker: str
    form: str
    document_type: DocumentType
    filing_date: date
    report_date: date | None
    accession_number: str
    primary_document: str

    @property
    def document_url(self) -> str:
        accession_no_dashes = self.accession_number.replace("-", "")
        cik_no_leading_zeros = str(int(self.cik))
        return (
            f"{_ARCHIVES_BASE}/{cik_no_leading_zeros}/{accession_no_dashes}/{self.primary_document}"
        )


class _RateLimiter:
    """Client-side politeness limiter — SEC asks for <=10 req/s; default is
    deliberately more conservative than the ceiling.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = min_interval_seconds
        self._lock = Lock()
        self._last_request_at: float | None = None

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self._last_request_at is not None:
                elapsed = now - self._last_request_at
                remaining = self._min_interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
            self._last_request_at = time.monotonic()


class SecEdgarClient:
    def __init__(
        self,
        *,
        user_agent: str,
        min_request_interval_seconds: float = 0.15,  # ~6-7 req/s, under SEC's ceiling
        timeout_seconds: float = 15.0,
    ) -> None:
        if "@" not in user_agent:
            raise SecEdgarError(
                "SEC EDGAR requires a User-Agent identifying the requester "
                "with a real contact (e.g. 'TradeGraph research@example.com')"
            )
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=timeout_seconds,
        )
        self._rate_limiter = _RateLimiter(min_request_interval_seconds)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SecEdgarClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def _get_json(self, url: str) -> dict[str, object]:
        self._rate_limiter.wait()
        response = self._client.get(url)
        response.raise_for_status()
        result: dict[str, object] = response.json()
        return result

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def fetch_filing_document(self, url: str) -> bytes:
        """Download the raw filing document — untouched bytes, no parsing.

        docs/04 Stage 2: this is what gets written to object storage before
        anything else happens to it.
        """
        self._rate_limiter.wait()
        response = self._client.get(url)
        response.raise_for_status()
        return response.content

    def get_cik_for_ticker(self, ticker: str) -> str:
        """Zero-padded 10-digit CIK for a ticker, per SEC's submissions API
        convention (`CIK0001045810.json`).
        """
        mapping = self._company_tickers()
        normalized = ticker.upper().strip()
        cik = mapping.get(normalized)
        if cik is None:
            raise SecEdgarError(f"no CIK found for ticker {ticker!r}")
        return cik

    def list_filings(
        self,
        ticker: str,
        *,
        forms: frozenset[str] = frozenset(SEC_FORM_TO_DOCUMENT_TYPE),
        since: date | None = None,
    ) -> list[FilingMetadata]:
        """Recent filings for one company, filtered to the requested forms.

        Only covers `filings.recent` (SEC paginates older history via
        separate files under `filings.files`) — sufficient for the V1
        controlled corpus (docs/03 §4: current 10-K + this year's 10-Qs +
        relevant 8-Ks), not a full historical backfill.
        """
        cik = self.get_cik_for_ticker(ticker)
        payload = self._get_json(_SUBMISSIONS_URL.format(cik=cik))

        company_name = str(payload.get("name", ""))
        tickers = payload.get("tickers")
        resolved_ticker = ticker.upper()
        if isinstance(tickers, list) and tickers:
            resolved_ticker = str(tickers[0])

        filings_obj = payload.get("filings")
        if not isinstance(filings_obj, dict):
            raise SecEdgarError(f"malformed submissions payload for CIK {cik}")
        recent = filings_obj.get("recent")
        if not isinstance(recent, dict):
            raise SecEdgarError(f"malformed 'filings.recent' for CIK {cik}")

        required_keys = (
            "form",
            "filingDate",
            "reportDate",
            "accessionNumber",
            "primaryDocument",
        )
        for key in required_keys:
            if key not in recent:
                raise SecEdgarError(f"'filings.recent' missing expected key {key!r}")

        results: list[FilingMetadata] = []
        count = len(recent["form"])
        for i in range(count):
            form = str(recent["form"][i])
            if form not in forms:
                continue

            document_type = SEC_FORM_TO_DOCUMENT_TYPE.get(form)
            if document_type is None:
                continue

            filing_date = _parse_date(str(recent["filingDate"][i]))
            if since is not None and filing_date < since:
                continue

            report_date_raw = recent["reportDate"][i]
            report_date = _parse_date(str(report_date_raw)) if report_date_raw else None

            results.append(
                FilingMetadata(
                    cik=cik,
                    company_name=company_name,
                    ticker=resolved_ticker,
                    form=form,
                    document_type=document_type,
                    filing_date=filing_date,
                    report_date=report_date,
                    accession_number=str(recent["accessionNumber"][i]),
                    primary_document=str(recent["primaryDocument"][i]),
                )
            )

        return results

    @lru_cache(maxsize=1)  # noqa: B019 — one client, one process-lifetime cache
    def _company_tickers(self) -> dict[str, str]:
        payload = self._get_json(_COMPANY_TICKERS_URL)
        mapping: dict[str, str] = {}
        for entry in payload.values():
            if not isinstance(entry, dict):
                continue
            ticker = entry.get("ticker")
            cik = entry.get("cik_str")
            if ticker is None or cik is None:
                continue
            mapping[str(ticker).upper()] = str(int(cik)).zfill(10)
        return mapping


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


DEFAULT_BENCHMARK_TICKERS: tuple[str, ...] = (
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
"""docs/15 D-18 — the resolved V1 benchmark company set."""
