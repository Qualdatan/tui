# qualdatan-tui

Terminal-GUI fuer [Qualdatan](https://github.com/GeneralPawz/Qualdatan).
Typer-basierte CLI mit Rich-Output, die [qualdatan-core](https://github.com/Qualdatan/core)
und [qualdatan-plugins](https://github.com/Qualdatan/plugins) orchestriert.

**Status**: frueh. Phase 1 hat `main.py` und die Console-Helpers aus dem
Umbrella extrahiert; Phase A stellt auf `qualdatan_tui.app` / `qualdatan_tui.console`
um und aktiviert den Entry-Point `qualdatan`.

## Install

```bash
pip install qualdatan-tui
qualdatan --help
```

## Dokumentation

- Live-Site: https://qualdatan.github.io/tui/
- Lokaler Preview: `pip install -e ".[docs]" && mkdocs serve`
- Docs-Policy und -Struktur: [CLAUDE.md](CLAUDE.md)

## Lizenz

AGPL-3.0-only — siehe [LICENSE](LICENSE).
