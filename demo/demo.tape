# Record the demo GIF:  brew install vhs && vhs demo/demo.tape
Output docs/assets/demo.gif

Set FontSize 16
Set Width 1300
Set Height 820
Set Theme "GitHub Dark"
Set TypingSpeed 40ms

Hide
Type "export PYTHONWARNINGS=ignore && clear" Enter
Show

Type "uv run python -m demo.run_demo 2>/dev/null" Sleep 500ms Enter
Sleep 25s
