# skilltest

**pytest for agent skills: prove your skill actually works.**

> Work in progress (phase 4 of 5). The full README lands with v1.

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

## Cost guard and CI gates

Before running, skilltest prints the plan and a cost estimate (learned from your
previous runs when it can). Above $5 it asks first; in CI it refuses unless you
pass `--yes`. `--dry-run` shows the plan without running anything. If the first
runs all fail (bad key, wrong model), it stops early and tells you what to fix.

```bash
skilltest run ./my-skill --dry-run
skilltest run ./my-skill --min-lift 0 --min-trigger-rate 80   # exit 1 if not met
```

## GitHub Action

Runs your evals on pull requests and keeps one results comment up to date.
See [`action/example-workflow.yml`](action/example-workflow.yml):

```yaml
- uses: akhilgarg07/skilltest@v0
  with:
    path: my-skill
    min-lift: "0"
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
node --test action/test/comment.test.js   # the action's PR-comment script
```

MIT licensed.
