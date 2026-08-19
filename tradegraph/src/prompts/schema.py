"""Prompt file schema (docs/17-ai-configuration-versioning.md, D-25).

Git is the production source of truth for prompts; LangSmith is for
experimentation and tracing only — the application never fetches a prompt
from a service at runtime. Every prompt version is an immutable YAML file
carrying a structured identity, not a bare `vN` filename.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ModelRequirements(BaseModel):
    """Generation settings — part of the prompt's behaviour, not a caller
    detail (docs/17). Required in the LLM cache key (docs/09) alongside
    model + prompt version + input.
    """

    model_config = ConfigDict(extra="allow")

    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, gt=0)


class PromptDefinition(BaseModel):
    """One immutable prompt version.

    Corresponds 1:1 to a `src/prompts/<node>/vN.yaml` file. `version` must
    match the `N` in the filename — enforced by the loader, not here, since
    the filename isn't visible to the model itself.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Stable identity across versions.")
    version: int = Field(ge=1)
    description: str = Field(min_length=1)
    model_requirements: ModelRequirements = Field(default_factory=ModelRequirements)
    variables: list[str] = Field(default_factory=list)
    prompt: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not _NAME_PATTERN.match(value):
            raise ValueError(
                f"prompt name {value!r} must be lower_snake_case (matches ^[a-z][a-z0-9_]*$)"
            )
        return value

    @field_validator("variables")
    @classmethod
    def _validate_variables_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("variables must not contain duplicates")
        return value

    def render(self, **kwargs: str) -> str:
        """Fill the template, failing loudly on a variable mismatch.

        A silently-ignored extra kwarg or a silently-missing variable is
        exactly the kind of error that should surface at call time, not
        appear as a malformed prompt reaching the model.
        """
        provided = set(kwargs)
        declared = set(self.variables)

        missing = declared - provided
        if missing:
            raise ValueError(
                f"prompt '{self.name}' v{self.version}: missing required "
                f"variables: {sorted(missing)}"
            )

        extra = provided - declared
        if extra:
            raise ValueError(
                f"prompt '{self.name}' v{self.version}: undeclared "
                f"variables passed: {sorted(extra)}"
            )

        return self.prompt.format(**kwargs)
