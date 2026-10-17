# Terminal demo for the README. Record with VHS (https://github.com/charmbracelet/vhs):
#
#   export ANTHROPIC_API_KEY=...      # the demo makes real Claude Code runs (~$1)
#   vhs docs/demo.tape                # writes docs/demo.gif
#
# Run it from the repository root with skilltest installed (pip install -e .).

Output docs/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1300
Set Height 720
Set Padding 24
Set TypingSpeed 45ms
Set Theme "Catppuccin Mocha"

Hide
Type "export PS1='$ ' && clear" Enter
Show

Type "# Does this skill actually help? Run the same tasks with and without it." Enter
Sleep 1.5s
Type "cat examples/release-notes/evals.yaml | grep -A1 'name:'" Enter
Sleep 3s

Type "skilltest run examples/release-notes --trials 3 --yes" Enter
# 18 agent runs, 4 at a time. Raise this if your machine or API is slower.
Sleep 75s

Type "skilltest badge examples/release-notes" Enter
Sleep 4s
