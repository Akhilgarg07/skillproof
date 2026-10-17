# skilltest

**pytest for agent skills: prove your skill actually works.**

> Work in progress (phase 1 of 5). The full README lands with v1.

`skilltest` runs each eval case N times **with** your skill installed and N
times **without** it, then reports trigger rate, pass-rate lift, and token and
latency deltas.

```bash
pip install skilltest
skilltest init ./my-skill     # scaffold evals.yaml with example cases
skilltest run ./my-skill      # run evals with and without the skill
```

Runners: `claude-code`, `codex`, `openai-compatible` (coming in phase 2), and
`mock` (scripted results for tests).

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

MIT licensed.
