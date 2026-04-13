# CLAUDE.md — qualdatan-tui

## Docs-Policy

Docs sind **nicht optional** und werden **mit dem Code** gepflegt. Die Site wird automatisch per GitHub Pages unter `https://qualdatan.github.io/tui/` veröffentlicht.

### Primäre API-Doku = Docstrings im Code

- Jede Änderung an öffentlicher API (Typer-Commands inklusive) → Docstring mitpflegen.
- **Stil**: Google-Docstring (`Args:`, `Returns:`, `Raises:`, `Example:`). Section-Marker englisch, Prosa darf deutsch sein.
- Typer-Commands: Der **erste Satz des Docstrings** wird von Typer als Command-Help verwendet. Kurz und präzise halten.
- Keine Redundanz: Docstring-Inhalt wird **nicht** in `docs/*.md` wiederholt.

### Narrative Docs unter `docs/`

- `docs/index.md` — Purpose, Install, `qualdatan --help`-Übersicht.
- `docs/architecture.md` — CLI-Struktur, Orchestrierung von core + plugins.
- `docs/api.md` — nur mkdocstrings-Direktiven (`::: qualdatan_tui.<modul>`).
- `docs/changelog.md` — Keep-a-Changelog.
- Neue Konzepte → neue MD-Datei + Eintrag in `mkdocs.yml` unter `nav`.

### Lokaler Preview

```bash
pip install -e ".[docs]"
mkdocs serve
```

### Deploy

Automatisch via `.github/workflows/docs.yml` bei Push auf `main`. Pages-Quelle einmalig auf Branch `gh-pages` setzen.
