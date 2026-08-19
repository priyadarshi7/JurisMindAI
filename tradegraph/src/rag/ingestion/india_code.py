"""India Code / Legislative Department ingestion adapter (NyayaGraph pivot,
docs/16 Phase 2). First source: the Constitution of India, fetched as the
official PDF from `legislative.gov.in` (Ministry of Law and Justice) —
confirmed live (2026-08-19) that both `indiacode.nic.in` and
`legislative.gov.in` 403 a request with no/generic User-Agent but return a
clean 200 to a normal browser-identified client, same lesson as
`sec_edgar.py`'s fair-access User-Agent requirement.

Only Part III (Fundamental Rights, Articles 12-35) is parsed for now —
scoped deliberately, not a placeholder: it directly serves constitutional
questions (Articles 19/21/22 detention/arrest rights) without taking on the
much harder problem of parsing the Constitution's non-article structure
(schedules, tables) in the same pass. Widening to other Parts is the same
`parse_articles` call with a different `(min_article, max_article)` bound.
"""

from __future__ import annotations

import io
import re
import uuid
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime

import pypdf
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.object_storage import ObjectStorageClient, build_raw_document_key
from src.models.orm import Chunk, ChunkType, Document, DocumentType, IngestionStatus
from src.rag.bm25.sparse_encoder import Bm25SparseEncoder
from src.rag.chunking.chunker import TableChunk, chunk_document
from src.rag.embeddings.ollama_embedder import OllamaEmbedder
from src.rag.ingestion.dedup import compute_content_hash
from src.rag.ingestion.parser import DocumentSection, ParsedDocument
from src.rag.vector.qdrant_store import ChunkPoint, QdrantStore

CONSTITUTION_ACT_CODE = "COI"
CONSTITUTION_AUTHORITY_TIER = 1  # Tier 1 — highest authority (docs/16)

_EM_DASH = chr(0x2014)
_REPLACEMENT_CHAR = chr(0xFFFD)
# Built via chr(), not pasted glyphs: found live (2026-08-19) that pasting
# the U+FFFD replacement-character glyph through this editing pipeline
# silently turned into U+2014 (em dash) instead, which made the
# garbled-title guard below check for the wrong character entirely — caught
# by test_parse_articles_drops_garbled_titles failing even though the code
# "looked" right. chr() sidesteps the pipeline's character substitution
# since the codepoint is spelled out in plain ASCII digits.

_ARTICLE_PATTERN = re.compile(
    r"\n\s*(\d{1,3}[A-Z]?)\.\s+([A-Z][^.]{0,120}?)[." + _EM_DASH + r"]",
    re.UNICODE,
)
# ❗ The replacement character is deliberately NOT a terminator here — found
# live: with it included, the lazy `[^.]{0,120}?` title group would stop
# matching right before the first U+FFFD it saw (since U+FFFD is itself a
# valid terminator), truncating a garbled title down to just its leading
# letter — which then looks clean and slips past the `_REPLACEMENT_CHAR in
# title` guard below. Leaving U+FFFD out of the terminator class means it
# stays *inside* the captured title (matched by `[^.]`), where the guard
# actually sees it.
_HEADER_NOISE = re.compile(r"THE CONSTITUTION OF INDIA\s*\n?")


class ConstitutionParseError(Exception):
    pass


def extract_pdf_page_text(pdf_bytes: bytes, *, start_page: int, end_page: int) -> str:
    """Concatenated text of pages `[start_page, end_page)`, 0-indexed."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(reader.pages[i].extract_text() for i in range(start_page, end_page))


def slice_between_markers(text: str, *, start_marker: str, end_marker: str) -> str:
    """Bound raw extracted text to one Part before splitting into articles.

    ❗ Required, not cosmetic — found live (2026-08-19): without this, the
    LAST kept article's body extends to the end of whatever page range was
    extracted (`body_end = len(text)` when there's no next article to stop
    at), so an `end_page` picked generously "to be safe" silently pulled an
    entire next Part (and beyond) into one article's text — "Article 35"
    absorbed 85,000 tokens including all of Part IV before this existed.
    """
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker) if start >= 0 else 0)
    if start < 0 or end < 0:
        raise ConstitutionParseError(
            f"could not find bounds {start_marker!r}..{end_marker!r} in extracted text"
        )
    return text[start:end]


def parse_articles(raw_text: str, *, min_article: int, max_article: int) -> ParsedDocument:
    """Split a bounded slice of Constitution body text into one
    `DocumentSection` per article, numbered `[min_article, max_article]`.

    ❗ Filters aggressively rather than trusting every regex hit — verified
    live against the real official PDF (2026-08-19): footnote/amendment
    markers ("1[Added by...", "2[Ins. by...") share the same "<number>.
    <text>" shape as a real article heading but use small numbers (1-9)
    that never collide with a real article number in any bounded Part of
    the Constitution, so bounding to `[min_article, max_article]`
    eliminates them structurally rather than by guessing at punctuation. A
    match whose title contains the Unicode replacement character (garbled
    font decoding, seen live on marginal amendment-history notes in this
    exact PDF) is dropped rather than kept corrupted — fewer, verifiably
    correct articles beats one presented-as-authoritative corrupted one.
    """
    cleaned = _HEADER_NOISE.sub(" ", raw_text)
    cleaned = cleaned.replace("\r", "").replace("\x0c", "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    matches = list(_ARTICLE_PATTERN.finditer(cleaned))
    kept: list[tuple[str, str, int, int]] = []  # (number, title, match_start, match_end)
    seen_numbers: set[str] = set()
    for m in matches:
        number, title = m.group(1), m.group(2).strip()
        n = int(re.match(r"\d+", number).group())  # type: ignore[union-attr]
        if not (min_article <= n <= max_article):
            continue
        if _REPLACEMENT_CHAR in title or number in seen_numbers:
            continue
        seen_numbers.add(number)
        kept.append((number, title, m.start(), m.end()))

    if not kept:
        raise ConstitutionParseError(f"no articles found in range {min_article}-{max_article}")

    sections: list[DocumentSection] = []
    dropped_garbled: list[str] = []
    truncated: list[str] = []
    for i, (number, title, _start, end) in enumerate(kept):
        body_end = kept[i + 1][2] if i + 1 < len(kept) else len(cleaned)
        # The known-benign artifact (this PDF's own separator dash decoding
        # as U+FFFD) is normalized away *before* the contamination check,
        # not after — otherwise every article's leading dash counts against
        # its own ascii ratio for no reason connected to real contamination.
        raw_body = cleaned[end:body_end].replace(_REPLACEMENT_CHAR, " - ")

        # Found live (2026-08-19): this exact official PDF interleaves a
        # regional-language (Kannada) rendering of some articles within the
        # same page range, using a font pypdf cannot decode into correct
        # Unicode — not U+FFFD (the garbled-title guard wouldn't catch it),
        # but plausible-looking Latin-alphabet gibberish. An unmatched
        # intermediate article (no boundary marker) lets that gibberish get
        # silently absorbed into whichever article came before it. Cutting
        # at the first contaminated window keeps the real English clause
        # that precedes the contamination — a genuine partial article is
        # far more useful than discarding the whole thing outright, and
        # still strictly safer than shipping it uncut.
        body = _truncate_at_contamination(raw_body)
        was_truncated = len(body) < len(raw_body)
        body = re.sub(r"\s+", " ", body).strip()

        if was_truncated:
            if len(body) < 20:
                # Contamination started at (or effectively at) the very
                # first character — nothing meaningful survived, same
                # "don't ship it" policy as a garbled title.
                dropped_garbled.append(f"Article {number}")
                continue
            truncated.append(f"Article {number}")
        # An article that was never truncated keeps whatever length it
        # genuinely has — several real Part III articles (e.g. Article 12,
        # "Definition") are legitimately short, and a length floor applied
        # unconditionally would drop real, uncontaminated content for no
        # reason connected to the actual problem this guards against.

        sections.append(
            DocumentSection(name=f"Article {number}", text=f"Article {number}. {title}.\n\n{body}")
        )

    if not sections:
        raise ConstitutionParseError(
            f"all articles in range {min_article}-{max_article} had garbled bodies"
        )
    if dropped_garbled:
        warnings.warn(
            f"parse_articles dropped {len(dropped_garbled)} article(s) with garbled bodies: "
            f"{', '.join(dropped_garbled)} — corpus is missing these, not silently corrupted",
            stacklevel=2,
        )
    if truncated:
        warnings.warn(
            f"parse_articles truncated {len(truncated)} article(s) at a contamination boundary "
            f"(kept the clean prefix only): {', '.join(truncated)} — corpus has partial text for "
            "these, not silently corrupted or complete",
            stacklevel=2,
        )

    return ParsedDocument(sections=sections)


def _is_mostly_ascii(text: str, *, min_ascii_ratio: float = 0.9) -> bool:
    if not text:
        return True
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return (ascii_count / len(text)) >= min_ascii_ratio


def _truncate_at_contamination(text: str, *, window: int = 60, step: int = 20) -> str:
    """The longest ASCII-clean prefix of `text`, cut at the first
    contaminated window rather than discarding the whole string.

    Uses an overlapping sliding window (`step` < `window`), not
    non-overlapping `window`-sized blocks — found live (2026-08-19) that a
    real clean prefix landing just under a large fixed window's boundary
    got the trailing contamination folded into the *same* check as the
    prefix, failing the ratio and discarding genuine content along with
    the garbage. A 60-char window needs a real run of contamination to
    trip (not one stray accented character), while the 20-char step keeps
    the actual cut point close to where contamination truly begins.
    """
    for start in range(0, len(text), step):
        if not _is_mostly_ascii(text[start : start + window]):
            return text[:start]
    return text


@dataclass(frozen=True)
class ConstitutionIngestionOutcome:
    document_id: uuid.UUID
    status: IngestionStatus
    chunks_created: int
    articles_parsed: int


async def ingest_constitution_part(
    pdf_bytes: bytes,
    *,
    source_url: str,
    start_page: int,
    end_page: int,
    part_start_marker: str,
    part_end_marker: str,
    min_article: int,
    max_article: int,
    storage: ObjectStorageClient,
    session: AsyncSession,
    embedder: OllamaEmbedder,
    bm25_encoder: Bm25SparseEncoder,
    qdrant_store: QdrantStore,
    raw_bucket: str,
    edition_date: datetime,
) -> ConstitutionIngestionOutcome:
    """Ingest one Part of the Constitution end to end — mirrors
    `src/rag/ingestion/pipeline.py::ingest_filing`'s shape (object storage
    first, content-hash dedup, chunk, embed, index Postgres + Qdrant) so the
    two adapters read as the same pattern applied to a different source,
    not two unrelated pipelines.
    """
    content_hash = compute_content_hash(pdf_bytes)
    raw_key = build_raw_document_key(
        source="legislative_gov_in",
        ticker=CONSTITUTION_ACT_CODE,
        document_type=DocumentType.CONSTITUTION.value,
        content_hash=content_hash,
        extension="pdf",
    )
    storage.put_object(bucket=raw_bucket, key=raw_key, body=pdf_bytes, content_type="application/pdf")

    raw_text = extract_pdf_page_text(pdf_bytes, start_page=start_page, end_page=end_page)
    part_text = slice_between_markers(
        raw_text, start_marker=part_start_marker, end_marker=part_end_marker
    )
    parsed = parse_articles(part_text, min_article=min_article, max_article=max_article)

    document = Document(
        company="Constitution of India",
        ticker=CONSTITUTION_ACT_CODE,
        document_type=DocumentType.CONSTITUTION,
        filing_date=edition_date,
        source="legislative_gov_in",
        source_url=source_url,
        content_hash=content_hash,
        raw_object_key=raw_key,
        raw_content_type="application/pdf",
        ingestion_status=IngestionStatus.PENDING,
        court=None,
        case_citation=None,
        act_code=CONSTITUTION_ACT_CODE,
        authority_tier=CONSTITUTION_AUTHORITY_TIER,
    )
    session.add(document)
    await session.flush()

    chunks = chunk_document(parsed)
    texts = [c.text for c in chunks]
    embeddings = embedder.embed_texts(texts)
    sparse_vectors = bm25_encoder.encode_documents(texts)

    chunk_rows: list[Chunk] = []
    qdrant_points: list[ChunkPoint] = []
    for chunk, embedding, sparse in zip(chunks, embeddings, sparse_vectors, strict=True):
        chunk_id = uuid.uuid4()
        table_title = table_headers = table_rows = None
        if isinstance(chunk, TableChunk):
            table_title, table_headers, table_rows = chunk.title, chunk.headers, chunk.rows

        chunk_rows.append(
            Chunk(
                id=chunk_id,
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                chunk_type=ChunkType(chunk.chunk_type),
                section=chunk.section,
                text=chunk.text,
                token_count=chunk.token_count,
                table_title=table_title,
                table_headers=table_headers,
                table_rows=table_rows,
                embedding_model=embedding.model,
                embedding_dimension=embedding.dimension,
                qdrant_point_id=str(chunk_id),
            )
        )
        qdrant_points.append(
            ChunkPoint(
                point_id=str(chunk_id),
                dense_vector=embedding.vector,
                sparse_indices=sparse.indices,
                sparse_values=sparse.values,
                payload={
                    "company": document.company,
                    "ticker": document.ticker,
                    "document_type": document.document_type.value,
                    "filing_date_ts": edition_date.toordinal(),
                    "tenant_id": None,
                    "document_id": str(document.id),
                    "chunk_id": str(chunk_id),
                    "text": chunk.text,
                    "section": chunk.section,
                    "chunk_type": chunk.chunk_type,
                    "act_code": CONSTITUTION_ACT_CODE,
                    "authority_tier": CONSTITUTION_AUTHORITY_TIER,
                },
            )
        )

    session.add_all(chunk_rows)
    qdrant_store.upsert_chunks(qdrant_points)

    document.ingestion_status = IngestionStatus.SUCCEEDED
    document.ingested_at = datetime.now(UTC)

    return ConstitutionIngestionOutcome(
        document_id=document.id,
        status=IngestionStatus.SUCCEEDED,
        chunks_created=len(chunks),
        articles_parsed=len(parsed.sections),
    )
