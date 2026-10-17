# skilltest

**pytest for agent skills: prove your skill actually works.**

> Work in progress (phase 3 of 5). The full README lands with v1.

`skilltest` runs each eval case N times **with** your skill installed and N
times **without** it, then reports trigger rate, pass-rate lift, and token and
latency deltas.

```bash
pip install skilltest
skilltest init ./my-skill     # scaffold evals.yaml with example cases
skilltest run ./my-skill      # run evals with and without the skill
skilltest report --format md  # re-render the latest run (terminal, md, html, json)
skilltest badge ./my-skill    # shields.io badge for your README
```

Every run saves `results.json`, `summary.json`, `report.md` and a
self-contained `report.html` under `.skilltest/runs/<timestamp>/`.

Numbers come with 95% intervals (Wilson for pass rates, Newcombe for the lift)
and a verdict: *helps*, *hurts* or *no clear effect*.

Runners:

| runner | how | skill install | trigger detection |
|---|---|---|---|
| `claude-code` | Claude Agent SDK | `<sandbox>/.claude/skills/<name>/` | `Skill` tool call |
| `codex` | `codex exec --json` | `<sandbox>/.agents/skills/<name>/` | shell command touching the skill folder |
| `openai-compatible` | Chat Completions tool loop | SKILL.md in the system prompt (approximate) | not measured |
| `mock` | scripted results, for tests | – | scripted |

Every run happens in a fresh temp directory. Your personal skills, settings and
instructions (~/.claude, ~/.codex, ~/.agents) are not loaded for either variant.

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

MIT licensed.
