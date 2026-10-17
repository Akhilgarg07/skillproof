# Terminal demo for the README. Record with VHS (https://github.com/charmbracelet/vhs):
#
#   export ANTHROPIC_API_KEY=...      # the demo makes 30 real Claude Code runs (~$1.50)
#   vhs docs/demo.tape                # writes docs/demo.gif
#
# Run it from the repository root with skilltest installed (pip install -e .).
# The ~1-2 minutes of agent runs are cut from the GIF; everything shown is real output.

Output docs/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1300
Set Height 540
Set Padding 24
Set TypingSpeed 40ms
Set Theme "Catppuccin Mocha"

Hide
Type "export PATH=$PWD/.venv/bin:$PATH PS1='$ ' && clear" Enter
Sleep 500ms
Show

Type "# Does this skill actually help? Same tasks, with and without it:" Enter
Sleep 1s
Type "grep -E '^  - name|prompt' examples/release-notes/evals.yaml" Enter
Sleep 4s
Ctrl+L

Type "skilltest run examples/release-notes --yes" Enter
Sleep 14s

# Skip the waiting while the agents work.
Hide
Wait+Screen@10m /report: /
Show
Sleep 9s

Type "skilltest badge examples/release-notes" Enter
Wait+Screen@30s /img\.shields\.io/
Sleep 5s
