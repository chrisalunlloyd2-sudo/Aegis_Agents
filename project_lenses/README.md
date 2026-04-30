# Project Lenses

Optional per-project lens files live here.

Examples:
- `compiler.txt`
- `ui-redesign.txt`
- `agent-runtime.txt`

Behavior:
- Normal turns do not inject the global `PROJECT_DIRECTIVE.txt` by default anymore.
- If a file here matches the current project lane name, that project lens is injected for that lane.
- Automation and background build loops may still include the global directive.
- The default fallback files remain `PROJECT_DIRECTIVE.txt` and `guardian_directive.txt`.
