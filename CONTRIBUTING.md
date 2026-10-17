# Contributing to skilltest

Thanks for helping! skilltest is meant to stay small and easy to read: prefer
plain code over clever abstractions, and explain *why* in comments when the
code can't.

## Setup

```bash
git clone https://github.com/akhilgarg07/skilltest && cd skilltest
uv venv && uv pip install -e ".[dev]"      # or: python -m venv .venv && pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
node --test action/test/comment.test.js     # only if you touch action/
```

Tests never call real APIs or agents. `tests/conftest.py` makes any test that
tries to start a real Claude Code or Codex session fail. Runner tests use
recorded transcripts in `tests/fixtures/` and fake executables or clients.

## Where things live

| path | what |
|---|---|
| `src/skilltest/cli.py` | the `skilltest` command (typer) |
| `src/skilltest/config.py` | the `evals.yaml` schema (pydantic) and loader |
| `src/skilltest/engine.py` | runs trials with/without the skill, sandboxes, fail-fast, saving |
| `src/skilltest/runners/` | one module per agent, plus `base.py` (the `Runner` interface) |
| `src/skilltest/parsers/` | turn an agent's transcript into an `AgentRun` (pure functions) |
| `src/skilltest/assertions/` | assertion types (`builtin.py`, `llm_judge.py`) |
| `src/skilltest/judges/` | judge models for `llm_judge` |
| `src/skilltest/stats.py` | pass rates, intervals, lift, verdicts |
| `src/skilltest/report/` | `summary.py` (all numbers, computed once) and one renderer per format |
| `action.yml`, `action/` | the GitHub Action |
| `examples/`, `leaderboard/` | example skills and the leaderboard tooling |

## Adding a runner (e.g. Gemini CLI)

1. Read the agent's **current** docs for its non-interactive mode, JSON output
   and how it discovers skills. Agent CLIs change often: don't rely on memory.
2. Create `src/skilltest/runners/<agent>.py` with a `Runner` subclass. Read the
   rules at the top of `runners/base.py`: only touch the sandbox, keep the user's
   personal config out of *both* variants, put infrastructure failures in `error`.
3. Put transcript parsing in `src/skilltest/parsers/<agent>.py` as pure
   functions, including trigger detection.
4. Register it in `RUNNERS` in `runners/__init__.py` and give it a sensible
   entry in `DEFAULT_COST_PER_RUN` (`estimate.py`).
5. Record one real transcript with and without a skill, scrub paths and IDs, save
   it under `tests/fixtures/`, and test the parser on it. Test the runner with a
   fake CLI (see `tests/test_codex.py`) or a fake client.
6. Add a row to the runners table in the README, including how triggers are detected.

## Adding an assertion type

Add a `BaseAssertion` subclass in `assertions/builtin.py` with a unique
`type: Literal["..."]` and an async `check()`, add it to the `Assertion` union in
`assertions/__init__.py`, document it in the README table and in the `init`
template comments, and add tests to `tests/test_assertions.py`.

## Pull requests

- Keep each PR to one change, with tests.
- Run ruff and pytest locally; CI runs them on Python 3.10–3.13.
- If you change `summary.json` fields, keep old ones (it's a contract for CI users)
  or bump `SCHEMA_VERSION` in `report/summary.py`.
