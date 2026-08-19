"""Section-aware chunker (docs/04 Stage 6, D-19).

Splits `ParsedDocument.sections` into ~700-token chunks with 100-token
overlap — the resolved V1 baseline (🎛️ tunable, benchmarked against the
frozen evaluation set later, not a permanent answer). Tables never pass
through this splitter: each `ExtractedTable` becomes exactly one table-type
chunk, whole, because a naively split table row is unciteable evidence.

Token counting uses tiktoken's `cl100k_base` encoding as an approximation.
It is **not** Qwen3's real tokenizer — no Python tokenizer for Qwen3 ships
here yet — so `chunk_size=700` currently means "700 cl100k_base tokens,"
not "700 Qwen3 tokens." The two are close enough for chunk-boundary
purposes but this is a known approximation, not a hidden one: swapping in
the real tokenizer is a same-shaped change to `_count_tokens` alone and
should happen before D-19's values are taken as final.
"""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

from src.rag.ingestion.parser import DocumentSection, ExtractedTable, ParsedDocument

CHUNK_SIZE_TOKENS = 700
CHUNK_OVERLAP_TOKENS = 100
CHUNKING_CONFIG_VERSION = "section_aware_v1"  # docs/17 run-manifest field

_ENCODING_NAME = "cl100k_base"
_encoding = tiktoken.get_encoding(_ENCODING_NAME)


class ChunkingError(Exception):
    pass


@dataclass(frozen=True)
class TextChunk:
    section: str
    chunk_index: int
    text: str
    token_count: int
    chunk_type: str = "text"


@dataclass(frozen=True)
class TableChunk:
    section: str | None
    chunk_index: int
    title: str | None
    headers: list[str]
    rows: list[list[str]]
    text: str  # linearized rendering — what gets embedded
    token_count: int
    chunk_type: str = "table"


Chunk = TextChunk | TableChunk


def chunk_document(
    parsed: ParsedDocument,
    *,
    chunk_size_tokens: int = CHUNK_SIZE_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Section-aware chunking with table-aware handling (D-19).

    Order: text chunks first (in document order across sections), then
    table chunks. Both carry `chunk_index` starting from 0 within their own
    type/section so callers can reconstruct citation order without
    depending on this function's internal ordering choice.
    """
    if overlap_tokens >= chunk_size_tokens:
        raise ChunkingError(
            f"overlap_tokens ({overlap_tokens}) must be smaller than "
            f"chunk_size_tokens ({chunk_size_tokens})"
        )

    chunks: list[Chunk] = []
    for section in parsed.sections:
        chunks.extend(
            _chunk_section(
                section, chunk_size_tokens=chunk_size_tokens, overlap_tokens=overlap_tokens
            )
        )

    for index, table in enumerate(parsed.tables):
        chunks.append(_table_to_chunk(table, chunk_index=index))

    return chunks


def _chunk_section(
    section: DocumentSection, *, chunk_size_tokens: int, overlap_tokens: int
) -> list[TextChunk]:
    if not section.text.strip():
        return []

    tokens = _encoding.encode(section.text)
    if len(tokens) <= chunk_size_tokens:
        return [
            TextChunk(
                section=section.name,
                chunk_index=0,
                text=section.text,
                token_count=len(tokens),
            )
        ]

    stride = chunk_size_tokens - overlap_tokens
    chunks: list[TextChunk] = []
    chunk_index = 0
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size_tokens, len(tokens))
        window = tokens[start:end]
        chunks.append(
            TextChunk(
                section=section.name,
                chunk_index=chunk_index,
                text=_encoding.decode(window),
                token_count=len(window),
            )
        )
        chunk_index += 1
        if end == len(tokens):
            break
        start += stride

    return chunks


def _table_to_chunk(table: ExtractedTable, *, chunk_index: int) -> TableChunk:
    linearized = _linearize_table(table)
    return TableChunk(
        section=table.section,
        chunk_index=chunk_index,
        title=table.title,
        headers=table.headers,
        rows=table.rows,
        text=linearized,
        token_count=len(_encoding.encode(linearized)),
    )


def _linearize_table(table: ExtractedTable) -> str:
    """Render a table as text for embedding, while `headers`/`rows` stay
    available structured on the chunk for exact display/citation — the
    embedding text and the citation-display representation are allowed to
    diverge, and here they do on purpose.
    """
    lines: list[str] = []
    if table.title:
        lines.append(table.title)
    if table.headers:
        lines.append(" | ".join(table.headers))
    for row in table.rows:
        lines.append(" | ".join(row))
    return "\n".join(lines)
