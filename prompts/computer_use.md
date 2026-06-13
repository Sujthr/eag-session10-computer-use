# computer_use

Drive real desktop applications on Windows using the five-layer cascade.

## Supported tasks

- `calculator <expression>` — evaluate arithmetic in Windows Calculator (Layer 2a)
- `vscode` — create hello_agent.py in VS Code via Electron CDP (Layer Electron)
- `browser_game [N moves]` — play N moves in the 2048 browser game (Layer 3 vision)

## Layer cascade

1. Layer 1 — extract: read AX tree directly, no LLM ($0)
2. Layer 2a — deterministic: hotkey recipes, no LLM ($0)
3. Layer 2b — a11y: AX markdown + cheap LLM (Gemini Flash-Lite, ¢¢)
4. Electron CDP: page tool via Chrome DevTools Protocol (when app is Electron)
5. Layer 3 — vision: screenshot + set-of-marks + vision LLM ($$$)

## Integration

```python
# Session 9 skills.py:
if skill.name == "computer":
    from computer_use.skill import run as computer_run
    return computer_run(goal)
```
