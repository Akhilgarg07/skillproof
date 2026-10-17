# Example skills

Four small skills that show each kind of result skillproof can give. Run any of
them with:

```bash
skillproof run examples/release-notes
```

| example | what the skill does | expected result |
|---|---|---|
| [`release-notes`](release-notes/) | Teaches house conventions an agent can't guess (section order, `[ACME-123]` ticket tags, author credits). | **Helps**: large positive lift. |
| [`python-style`](python-style/) | Generic clean-code advice the agent already follows. | **No clear effect**: same pass rate, more tokens. |
| [`over-eager-formatter`](over-eager-formatter/) | Triggers on every Python edit and reformats files nobody asked it to touch. | **Hurts**: negative lift, more tokens. |
| [`stale-docs`](stale-docs/) | Outdated docs for a library. Code that trusts them is silently wrong. | Bonus: strong agents read the source and ignore the skill, but pay for it in tokens. |

Each example is a normal skill folder (`SKILL.md`) with an `evals.yaml` and a
`fixtures/` folder that gets copied into a fresh sandbox for every run.

Results from our own runs (Claude Code, `claude-opus-5-5`). release-notes used
10 trials per variant; the others are 1–2-trial smoke runs, so treat those as
directional and run them with `--trials 10` before quoting:

| example | lift | cost Δ |
|---|---:|---:|
| release-notes | +100% (95% CI +77% to +100%) | +15% |
| python-style | ±0% | +16% |
| over-eager-formatter | −100% | +63% |
| stale-docs | ±0% | +13% |
