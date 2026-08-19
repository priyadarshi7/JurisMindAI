"""Prompt repository loader (docs/17-ai-configuration-versioning.md, D-25).

Validates every prompt file's identity and declared variables at process
startup, not at call time (docs/16 Phase 0 checklist) — a malformed prompt
file should fail the deploy, not the first research job that happens to
reach that node.

Directory layout is fixed by docs/09 §9 — one directory per LLM-calling graph
node, eight in total. Adding a directory means adding a node.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.prompts.schema import PromptDefinition

REQUIRED_NODES: frozenset[str] = frozenset(
    {
        "planner",
        "query_rewriter",
        "evidence_extractor",
        "verifier",
        "contradiction",
        "synthesizer",
        "critic",
        "citation_validator",
    }
)

_VERSION_FILENAME_PATTERN = re.compile(r"^v(\d+)\.ya?ml$")


class PromptLoadError(Exception):
    """Raised when a prompt file is malformed or the repository is incomplete.

    Deliberately not caught anywhere near startup — an invalid prompt
    repository must fail the deploy.
    """


class PromptRepository:
    """Loads and validates every versioned prompt under a root directory."""

    def __init__(self, root: Path, *, require_all_nodes: bool = True) -> None:
        self._root = root
        self._prompts: dict[str, dict[int, PromptDefinition]] = {}
        self._load_all(require_all_nodes=require_all_nodes)

    def _load_all(self, *, require_all_nodes: bool) -> None:
        if not self._root.is_dir():
            raise PromptLoadError(f"prompt root does not exist: {self._root}")

        # __pycache__ appears once this package (or a node dir, which is not
        # itself a package but shares the parent) has been imported anywhere
        # in the process — exclude dunder directories rather than treating
        # bytecode-cache noise as an unexpected prompt node.
        found_nodes = {
            path.name
            for path in self._root.iterdir()
            if path.is_dir() and not path.name.startswith("__")
        }

        if require_all_nodes:
            missing = REQUIRED_NODES - found_nodes
            if missing:
                raise PromptLoadError(
                    f"missing required prompt node directories: {sorted(missing)}"
                )

        unexpected = found_nodes - REQUIRED_NODES
        if unexpected:
            raise PromptLoadError(
                f"unexpected prompt node directories (not in the fixed §9 "
                f"eight): {sorted(unexpected)}"
            )

        for node in sorted(found_nodes):
            self._load_node(node)

    def _load_node(self, node: str) -> None:
        node_dir = self._root / node
        versions: dict[int, PromptDefinition] = {}

        for file_path in sorted(node_dir.iterdir()):
            if not file_path.is_file():
                continue

            match = _VERSION_FILENAME_PATTERN.match(file_path.name)
            if not match:
                raise PromptLoadError(f"{file_path}: filename must match 'vN.yaml' (e.g. v1.yaml)")
            filename_version = int(match.group(1))

            definition = self._load_file(file_path)

            if definition.version != filename_version:
                raise PromptLoadError(
                    f"{file_path}: filename declares version {filename_version} "
                    f"but the file's 'version' field is {definition.version}"
                )

            if filename_version in versions:
                raise PromptLoadError(f"{node}: duplicate version {filename_version}")

            versions[filename_version] = definition

        if not versions:
            raise PromptLoadError(f"{node}: no prompt versions found")

        self._prompts[node] = versions

    @staticmethod
    def _load_file(file_path: Path) -> PromptDefinition:
        try:
            raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise PromptLoadError(f"{file_path}: invalid YAML: {exc}") from exc

        if not isinstance(raw, dict):
            raise PromptLoadError(f"{file_path}: must contain a YAML mapping")

        try:
            return PromptDefinition.model_validate(raw)
        except ValidationError as exc:
            raise PromptLoadError(f"{file_path}: {exc}") from exc

    def get(self, node: str, version: int) -> PromptDefinition:
        try:
            return self._prompts[node][version]
        except KeyError as exc:
            raise KeyError(f"no prompt for node={node!r} version={version}") from exc

    def latest_version(self, node: str) -> int:
        """Highest committed version number.

        Not a runtime "use whatever is newest" default — call sites should
        pin an explicit version and only bump it through the promotion path
        in docs/17 (edit -> evaluate -> compare -> commit).
        """
        return max(self._prompts[node])

    def nodes(self) -> list[str]:
        return sorted(self._prompts)

    def versions(self, node: str) -> list[int]:
        return sorted(self._prompts[node])
