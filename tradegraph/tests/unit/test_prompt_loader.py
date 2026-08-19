"""Unit tests for src.prompts.loader.

Exercises both the real `src/prompts/` repository (must always validate —
this is the startup check apps/api/main.py relies on) and synthetic
tmp_path repositories for the failure modes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.prompts.loader import REQUIRED_NODES, PromptLoadError, PromptRepository

REAL_PROMPTS_ROOT = Path(__file__).resolve().parents[2] / "src" / "prompts"


def test_real_repository_loads_and_validates() -> None:
    repo = PromptRepository(REAL_PROMPTS_ROOT)
    assert set(repo.nodes()) == REQUIRED_NODES


def test_real_repository_every_node_has_v1() -> None:
    """Every node's v1 must exist and stay loadable — immutable, never the
    *only* version a node may accumulate (evidence_extractor, verifier,
    contradiction, and synthesizer have since gained a v2 for
    index-based structured output; see their v2.yaml descriptions).
    """
    repo = PromptRepository(REAL_PROMPTS_ROOT)
    for node in REQUIRED_NODES:
        assert 1 in repo.versions(node)
        definition = repo.get(node, 1)
        assert definition.version == 1
        assert definition.prompt.strip()


def _write_prompt(path: Path, *, name: str, version: int) -> None:
    path.write_text(
        f"""\
name: {name}
version: {version}
description: test
variables: []
prompt: "hello"
""",
        encoding="utf-8",
    )


def _make_minimal_valid_repo(root: Path) -> None:
    for node in REQUIRED_NODES:
        node_dir = root / node
        node_dir.mkdir(parents=True)
        _write_prompt(node_dir / "v1.yaml", name=f"{node}_prompt", version=1)


def test_missing_required_node_raises(tmp_path: Path) -> None:
    _make_minimal_valid_repo(tmp_path)
    # Remove one required node entirely.
    for f in (tmp_path / "critic").iterdir():
        f.unlink()
    (tmp_path / "critic").rmdir()

    with pytest.raises(PromptLoadError, match="missing required prompt node"):
        PromptRepository(tmp_path)


def test_unexpected_node_directory_raises(tmp_path: Path) -> None:
    _make_minimal_valid_repo(tmp_path)
    (tmp_path / "not_a_real_node").mkdir()
    _write_prompt(tmp_path / "not_a_real_node" / "v1.yaml", name="rogue", version=1)

    with pytest.raises(PromptLoadError, match="unexpected prompt node"):
        PromptRepository(tmp_path)


def test_version_filename_mismatch_raises(tmp_path: Path) -> None:
    _make_minimal_valid_repo(tmp_path)
    # File declares version=1 internally but is named v2.yaml.
    _write_prompt(tmp_path / "planner" / "v2.yaml", name="planner_prompt", version=1)

    with pytest.raises(PromptLoadError, match="filename declares version"):
        PromptRepository(tmp_path)


def test_bad_filename_raises(tmp_path: Path) -> None:
    _make_minimal_valid_repo(tmp_path)
    (tmp_path / "planner" / "version_one.yaml").write_text("name: x", encoding="utf-8")

    with pytest.raises(PromptLoadError, match=r"must match 'vN\.yaml'"):
        PromptRepository(tmp_path)


def test_empty_node_directory_raises(tmp_path: Path) -> None:
    _make_minimal_valid_repo(tmp_path)
    for f in (tmp_path / "verifier").iterdir():
        f.unlink()

    with pytest.raises(PromptLoadError, match="no prompt versions found"):
        PromptRepository(tmp_path)


def test_latest_version_picks_highest(tmp_path: Path) -> None:
    _make_minimal_valid_repo(tmp_path)
    _write_prompt(tmp_path / "planner" / "v2.yaml", name="planner_prompt", version=2)
    _write_prompt(tmp_path / "planner" / "v3.yaml", name="planner_prompt", version=3)

    repo = PromptRepository(tmp_path)
    assert repo.latest_version("planner") == 3
    assert repo.versions("planner") == [1, 2, 3]
