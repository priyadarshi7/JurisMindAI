"""Unit tests for src.rag.chunking.chunker (D-19: 700/100 token baseline)."""

from __future__ import annotations

import pytest
import tiktoken

from src.rag.chunking.chunker import (
    ChunkingError,
    TableChunk,
    TextChunk,
    chunk_document,
)
from src.rag.ingestion.parser import DocumentSection, ExtractedTable, ParsedDocument

_encoding = tiktoken.get_encoding("cl100k_base")


def _long_text(word_count: int) -> str:
    return " ".join(f"word{i}" for i in range(word_count))


def test_short_section_produces_one_chunk() -> None:
    parsed = ParsedDocument(
        sections=[DocumentSection(name="Item 1A", text="A short risk factor paragraph.")]
    )
    chunks = chunk_document(parsed)
    assert len(chunks) == 1
    assert isinstance(chunks[0], TextChunk)
    assert chunks[0].section == "Item 1A"
    assert chunks[0].chunk_index == 0


def test_empty_section_produces_no_chunks() -> None:
    parsed = ParsedDocument(sections=[DocumentSection(name="Item 9", text="")])
    assert chunk_document(parsed) == []


def test_long_section_splits_into_multiple_chunks_with_overlap() -> None:
    text = _long_text(2000)  # well over 700 tokens
    parsed = ParsedDocument(sections=[DocumentSection(name="Item 7", text=text)])

    chunks = chunk_document(parsed, chunk_size_tokens=700, overlap_tokens=100)

    assert len(chunks) > 1
    for chunk in chunks:
        assert isinstance(chunk, TextChunk)
        assert chunk.token_count <= 700
    # chunk_index increases monotonically within the section
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_overlap_actually_repeats_tokens_between_consecutive_chunks() -> None:
    text = _long_text(1600)
    parsed = ParsedDocument(sections=[DocumentSection(name="Item 7", text=text)])

    chunks = chunk_document(parsed, chunk_size_tokens=700, overlap_tokens=100)
    assert len(chunks) >= 2

    first_tokens = _encoding.encode(chunks[0].text)
    second_tokens = _encoding.encode(chunks[1].text)
    # The last `overlap` tokens of chunk 0 should equal the first `overlap`
    # tokens of chunk 1 — that is what "overlap" means operationally.
    assert first_tokens[-100:] == second_tokens[:100]


def test_overlap_must_be_smaller_than_chunk_size() -> None:
    parsed = ParsedDocument(sections=[DocumentSection(name="Item 1", text="text")])
    with pytest.raises(ChunkingError):
        chunk_document(parsed, chunk_size_tokens=100, overlap_tokens=100)


def test_table_becomes_single_whole_chunk_never_split() -> None:
    table = ExtractedTable(
        title="Revenue by segment",
        headers=["Segment", "FY2025"],
        rows=[["Data Center", "115186"], ["Gaming", "11350"]],
        section=None,
    )
    parsed = ParsedDocument(sections=[], tables=[table])

    chunks = chunk_document(parsed)
    assert len(chunks) == 1
    assert isinstance(chunks[0], TableChunk)
    assert chunks[0].headers == ["Segment", "FY2025"]
    assert chunks[0].rows == [["Data Center", "115186"], ["Gaming", "11350"]]


def test_table_chunk_preserves_structured_fields_separately_from_text() -> None:
    table = ExtractedTable(
        title="Revenue",
        headers=["A", "B"],
        rows=[["1", "2"]],
        section="Item 7",
    )
    parsed = ParsedDocument(sections=[], tables=[table])
    chunk = chunk_document(parsed)[0]
    assert isinstance(chunk, TableChunk)

    assert "Revenue" in chunk.text
    assert "A | B" in chunk.text
    assert "1 | 2" in chunk.text
    # Structured access must not require re-parsing the linearized text.
    assert chunk.headers == ["A", "B"]
    assert chunk.rows == [["1", "2"]]


def test_multiple_sections_and_tables_together() -> None:
    parsed = ParsedDocument(
        sections=[
            DocumentSection(name="Item 1A", text="Risk factors text."),
            DocumentSection(name="Item 7", text="MD&A text."),
        ],
        tables=[
            ExtractedTable(title="T1", headers=["X"], rows=[["1"]], section=None),
        ],
    )
    chunks = chunk_document(parsed)
    text_chunks = [c for c in chunks if isinstance(c, TextChunk)]
    table_chunks = [c for c in chunks if isinstance(c, TableChunk)]

    assert len(text_chunks) == 2
    assert len(table_chunks) == 1
    assert {c.section for c in text_chunks} == {"Item 1A", "Item 7"}
