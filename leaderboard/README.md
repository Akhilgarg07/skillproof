# Leaderboard tooling

Run skilltest against many skills and publish a markdown table
(`LEADERBOARD.md`, written by `run` and `render`).

```bash
pip install -e .                                   # from the repo root
python leaderboard/leaderboard.py run --dry-run    # plans and cost estimates only
python leaderboard/leaderboard.py run --trials 10  # run every entry in skills.yaml
python leaderboard/leaderboard.py run --only release-notes
python leaderboard/leaderboard.py render           # rebuild LEADERBOARD.md from results/
```

- **Add a skill:** add an entry to [`skills.yaml`](skills.yaml) and write its tasks in
  `evals/<name>.yaml` (start from [`evals/TEMPLATE.yaml`](evals/TEMPLATE.yaml)).
- **Results** are saved as `results/<name>.json` (commit them) and rendered to
  `LEADERBOARD.md`. Transcripts and clones go to `.cache/` (ignored by git).
- **Cost guard:** each entry prints its estimate first and stops above $5 unless you
  pass `--yes` (or raise `--confirm-above`).

## Safety

- The evals always come from this folder, never from the repo being tested, so a
  third-party repo can't run shell commands through `command` assertions.
- The agent still reads the skill's files, and a malicious skill can try to make it
  run commands. Run the leaderboard in a throwaway VM or container, with API keys
  that have spending limits.

## Fairness

Lift measures one set of tasks with one agent and model. Write tasks that match
what the skill claims to do, publish them in `evals/`, use 10+ trials, and link the
evals next to any number you share.
