"""The evals.yaml schema and loader.

Paths in evals.yaml are relative to the evals.yaml file. `load_config()`
returns a config with every path resolved to an absolute one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

from skilltest.assertions import ASSERTION_TYPES, Assertion
from skilltest.errors import ConfigError
from skilltest.runners import RUNNERS, get_runner_class

CONFIG_NAMES = ("evals.yaml", "evals.yml")


class JudgeConfig(BaseModel):
    """Which model grades `llm_judge` assertions.

    `auto` picks a vendor different from the agent under test (Claude agents
    are judged by an OpenAI model and vice versa) to avoid self-grading.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["auto", "anthropic", "openai", "mock"] = "auto"
    model: str | None = None  # None = the provider's default judge model
    base_url: str | None = None  # for OpenAI-compatible judge endpoints
    api_key_env: str | None = None  # env var holding the key; None = provider default


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    fixtures: Path | None = None  # folder copied into each run's sandbox
    trials: int | None = Field(default=None, ge=1, le=100)  # overrides the top-level value
    timeout: float | None = Field(default=None, gt=0)  # seconds; overrides top-level
    # false = a negative case: the skill should NOT activate for this prompt.
    should_trigger: bool = True
    assertions: list[Assertion] = Field(default_factory=list, alias="assert")


class EvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill: Path = Path(".")
    runner: str = "claude-code"
    model: str | None = None  # passed to the runner; None = the agent's default
    runner_options: dict[str, Any] = Field(default_factory=dict)
    trials: int = Field(default=5, ge=1, le=100)
    timeout: float = Field(default=300, gt=0)  # seconds per run
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    cases: list[Case] = Field(min_length=1)

    _path: Path | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _check(self) -> EvalConfig:
        if self.runner not in RUNNERS:
            valid = ", ".join(RUNNERS)
            raise ValueError(f"unknown runner {self.runner!r}. Valid runners: {valid}")
        if self.model is None and get_runner_class(self.runner).requires_model:
            raise ValueError(f"the {self.runner} runner needs `model:` (e.g. model: gpt-5.1)")
        seen: set[str] = set()
        for case in self.cases:
            if case.name in seen:
                raise ValueError(f"duplicate case name {case.name!r}; case names must be unique")
            seen.add(case.name)
        return self

    @property
    def path(self) -> Path | None:
        """The evals.yaml this config was loaded from."""
        return self._path

    def trials_for(self, case: Case) -> int:
        return case.trials or self.trials

    def timeout_for(self, case: Case) -> float:
        return case.timeout or self.timeout

    def uses_judge(self) -> bool:
        return any(a.type == "llm_judge" for c in self.cases for a in c.assertions)


def find_config(path: Path) -> Path:
    """Accept either an evals.yaml file or a folder containing one."""
    if path.is_file():
        return path
    if path.is_dir():
        for name in CONFIG_NAMES:
            if (path / name).is_file():
                return path / name
        raise ConfigError(
            f"No evals.yaml in {path}",
            hint=f"Create one with: skilltest init {path}",
        )
    raise ConfigError(f"Path not found: {path}", hint="Pass a skill folder or an evals.yaml file.")


def format_validation_error(exc: ValidationError, source: Path | str) -> str:
    """Turn pydantic errors into lines like `cases[0].assert[1]: unknown field 'vale'`."""
    lines = []
    for err in exc.errors():
        loc = ""
        for part in err["loc"]:
            if isinstance(part, int):
                loc += f"[{part}]"
            elif part in ASSERTION_TYPES:
                continue  # pydantic adds the union tag to the path; it's noise for users
            else:
                loc += f".{part}" if loc else str(part)
        msg = err["msg"]
        if err["type"] == "extra_forbidden":
            msg = f"unknown field {err['loc'][-1]!r} (typo?)"
        elif err["type"] == "missing":
            msg = "missing required field"
        elif err["type"] == "union_tag_invalid":
            msg = f"unknown assertion type {err['input'].get('type')!r}. " + (
                "Valid types: " + ", ".join(ASSERTION_TYPES)
            )
        elif msg.startswith("Value error, "):
            msg = msg.removeprefix("Value error, ")
        lines.append(f"  {loc or '(top level)'}: {msg}")
    return f"{source} is invalid:\n" + "\n".join(lines)


def parse_config(data: Any, base_dir: Path, source: Path | str = "evals.yaml") -> EvalConfig:
    """Validate raw YAML data and resolve paths relative to `base_dir`."""
    if not isinstance(data, dict):
        raise ConfigError(
            f"{source} must be a YAML mapping (key: value pairs).",
            hint="Run `skilltest init` to see an example evals.yaml.",
        )
    try:
        config = EvalConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            format_validation_error(exc, source),
            hint="Fix the fields above. See `skilltest init` output for a working example.",
        ) from exc

    base_dir = base_dir.resolve()
    config.skill = (base_dir / config.skill).resolve()
    for case in config.cases:
        if case.fixtures is None:
            continue
        case.fixtures = (base_dir / case.fixtures).resolve()
        if not case.fixtures.is_dir():
            raise ConfigError(
                f"Case {case.name!r}: fixtures folder not found: {case.fixtures}",
                hint="`fixtures:` is a folder, relative to evals.yaml, copied into each sandbox.",
            )

    _validate_runner_options(config, source)
    return config


def _validate_runner_options(config: EvalConfig, source: Path | str) -> None:
    options_model = get_runner_class(config.runner).Options
    try:
        options_model.model_validate(config.runner_options)
    except ValidationError as exc:
        message = format_validation_error(exc, f"{source} (runner_options for {config.runner})")
        raise ConfigError(
            message, hint=f"Check the `runner_options` supported by the {config.runner} runner."
        ) from exc


def load_config(path: Path) -> EvalConfig:
    config_path = find_config(path).resolve()
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"{config_path} is not valid YAML: {exc}",
            hint="Check indentation and quoting near the line mentioned above.",
        ) from exc
    config = parse_config(data, config_path.parent, source=config_path.name)
    config._path = config_path
    return config
