from __future__ import annotations

from pathlib import Path

import pytest

from skilltest.config import load_config, parse_config
from skilltest.errors import ConfigError

CASE = {"name": "c1", "prompt": "hi", "assert": [{"type": "contains", "value": "x"}]}


def test_minimal_config_defaults(write_evals, skill_dir: Path) -> None:
    config = load_config(write_evals({"cases": [{"name": "c1", "prompt": "hi"}]}))
    assert config.skill == skill_dir.resolve()
    assert config.trials == 5
    assert config.timeout == 300
    assert config.judge.provider == "auto"
    assert config.cases[0].should_trigger is True
    assert config.cases[0].assertions == []
    assert config.path == (skill_dir / "evals.yaml").resolve()


def test_accepts_folder_or_file(write_evals, skill_dir: Path) -> None:
    path = write_evals({"cases": [CASE]})
    assert load_config(skill_dir).path == load_config(path).path


def test_paths_resolve_relative_to_evals_file(write_evals, skill_dir: Path) -> None:
    case = {**CASE, "fixtures": "./fixtures/case1"}
    config = load_config(write_evals({"cases": [case]}))
    assert config.cases[0].fixtures == (skill_dir / "fixtures" / "case1").resolve()


def test_all_assertion_types_parse(write_evals) -> None:
    asserts = [
        {"type": "contains", "value": "a"},
        {"type": "not_contains", "value": "b"},
        {"type": "regex", "pattern": r"\d+"},
        {"type": "file_exists", "path": "out.txt"},
        {"type": "file_contains", "path": "out.txt", "value": "c"},
        {"type": "command", "run": "true"},
        {"type": "max_tokens", "value": 100},
        {"type": "llm_judge", "rubric": "good"},
    ]
    config = load_config(write_evals({"cases": [{**CASE, "assert": asserts}]}))
    assert [a.type for a in config.cases[0].assertions] == [a["type"] for a in asserts]
    assert config.uses_judge()


def test_per_case_overrides(write_evals) -> None:
    config = load_config(
        write_evals({"trials": 3, "cases": [{**CASE, "trials": 7}, CASE | {"name": "c2"}]})
    )
    assert [config.trials_for(c) for c in config.cases] == [7, 3]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"cases": []}, "cases: List should have at least 1 item"),
        (
            {
                "cases": [
                    {"name": "c", "prompt": "p", "assert": [{"type": "contain", "value": "x"}]}
                ]
            },
            "cases[0].assert[0]: unknown assertion type 'contain'. Valid types: contains",
        ),
        (
            {
                "cases": [
                    {"name": "c", "prompt": "p", "assert": [{"type": "contains", "vale": "x"}]}
                ]
            },
            "cases[0].assert[0].vale: unknown field 'vale' (typo?)",
        ),
        (
            {"cases": [{"name": "c", "prompt": "p", "assert": [{"type": "contains"}]}]},
            "cases[0].assert[0].value: missing required field",
        ),
        (
            {
                "cases": [
                    {
                        "name": "c",
                        "prompt": "p",
                        "assert": [{"type": "file_exists", "path": "../x"}],
                    }
                ]
            },
            "must be a relative path inside the sandbox",
        ),
        (
            {
                "cases": [
                    {"name": "c", "prompt": "p", "assert": [{"type": "regex", "pattern": "("}]}
                ]
            },
            "invalid regular expression",
        ),
        ({"runner": "gpt-agent", "cases": [CASE]}, "unknown runner 'gpt-agent'. Valid runners:"),
        ({"cases": [CASE, CASE]}, "duplicate case name 'c1'"),
        ({"trials": 0, "cases": [CASE]}, "trials: Input should be greater than or equal to 1"),
        ({"tirals": 3, "cases": [CASE]}, "tirals: unknown field 'tirals' (typo?)"),
        (
            {"cases": [CASE], "runner_options": {"defualt": {}}},
            "defualt: unknown field 'defualt' (typo?)",
        ),
    ],
)
def test_validation_errors_are_readable(data: dict, expected: str) -> None:
    data = {"runner": "mock", **data}
    with pytest.raises(ConfigError) as exc:
        parse_config(data, Path("."))
    assert expected in exc.value.message
    assert exc.value.hint


def test_missing_fixtures_folder(write_evals) -> None:
    with pytest.raises(ConfigError, match="fixtures folder not found"):
        load_config(write_evals({"cases": [{**CASE, "fixtures": "./nope"}]}))


def test_not_a_mapping() -> None:
    with pytest.raises(ConfigError, match="must be a YAML mapping"):
        parse_config(["a", "b"], Path("."))


def test_invalid_yaml(skill_dir: Path) -> None:
    (skill_dir / "evals.yaml").write_text("cases: [\n")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(skill_dir)


def test_no_evals_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"No evals\.yaml") as exc:
        load_config(tmp_path)
    assert "skilltest init" in exc.value.hint
