# Architecture

`qualdatan-tui` ist die Terminal-Frontend-Schicht. Sie enthält **keine** Analyse-Logik, nur Orchestrierung.

## Aufbau

| Modul | Verantwortlich für |
|-------|--------------------|
| `qualdatan_tui.app` | Typer-App, Command-Registrierung, Entry-Point `qualdatan` |
| `qualdatan_tui.console` | Rich-Console-Helpers, einheitliches Output-Format |

## Orchestrierung

Die TUI bindet sich an:

- [`qualdatan-core`](https://github.com/Qualdatan/core) — Pipeline-Primitives (PDF, QDPX, LLM-Kodierung).
- [`qualdatan-plugins`](https://github.com/Qualdatan/plugins) — Bundle-Management.

Abhängigkeiten werden in `pyproject.toml` strikt mit `>=0.1,<0.2` gepinnt, um Breaking Changes in `core` oder `plugins` nicht unbeabsichtigt einzusammeln.

## Lizenz & SPDX

AGPL-3.0-only. Neue Quelldateien beginnen mit:

```python
# SPDX-License-Identifier: AGPL-3.0-only
```
