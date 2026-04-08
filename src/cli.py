"""Interaktives CLI für die Analyse-Pipeline."""

import sys
from pathlib import Path

from .config import TRANSCRIPTS_DIR, CODEBASES_DIR, DEFAULT_RECIPE
from .recipe import list_recipes, load_recipe, list_codebases, load_codebase


def _pick(prompt: str, options: list[str], allow_skip: bool = False) -> str | None:
    """Zeigt eine nummerierte Auswahl und gibt die Wahl zurück."""
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")
    if allow_skip:
        print(f"  [0] Überspringen")

    while True:
        try:
            choice = input("\nAuswahl: ").strip()
            if allow_skip and choice == "0":
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except (ValueError, EOFError):
            pass
        print("  Ungültige Auswahl, bitte erneut versuchen.")


def _pick_multiple(prompt: str, options: list[str]) -> list[str]:
    """Zeigt eine nummerierte Auswahl, erlaubt Mehrfachauswahl oder 'alle'."""
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")
    print(f"  [a] Alle auswählen")

    while True:
        try:
            choice = input("\nAuswahl (Nummern kommagetrennt, oder 'a' für alle): ").strip()
            if choice.lower() == "a":
                return options
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
            selected = [options[i] for i in indices if 0 <= i < len(options)]
            if selected:
                return selected
        except (ValueError, EOFError, IndexError):
            pass
        print("  Ungültige Auswahl, bitte erneut versuchen.")


def interactive_setup() -> dict:
    """Führt den interaktiven Setup-Dialog und gibt die Konfiguration zurück."""
    print("=" * 60)
    print("  Qualitative Analyse – Interaktive Konfiguration")
    print("=" * 60)

    # 1. Transkripte auswählen
    transcripts = sorted(f.name for f in TRANSCRIPTS_DIR.glob("*.docx"))
    if not transcripts:
        print(f"\nKeine .docx-Dateien in {TRANSCRIPTS_DIR} gefunden.")
        print("Bitte lege deine Transkripte dort ab und starte erneut.")
        sys.exit(1)

    print(f"\nGefundene Transkripte in {TRANSCRIPTS_DIR}:")
    selected_transcripts = _pick_multiple(
        "Welche Transkripte sollen analysiert werden?",
        transcripts,
    )
    print(f"  → {len(selected_transcripts)} Transkript(e) ausgewählt")

    # 2. Methode (Recipe) auswählen
    recipes = list_recipes()
    if not recipes:
        print(f"\nKeine Recipes gefunden. Bitte prüfe den Ordner 'recipes/'.")
        sys.exit(1)

    recipe_names = [f"{r['id']} – {r['name']}" for r in recipes]
    recipe_choice = _pick("Welche Analyse-Methode?", recipe_names)
    recipe_id = recipe_choice.split(" – ")[0]
    print(f"  → Methode: {recipe_id}")

    # 3. Codebasis?
    codebases = list_codebases()
    codebase_name = None
    if codebases:
        use_codebase = _pick(
            "Möchtest du eine vorhandene Codebasis verwenden?",
            ["Ja, vorhandene Codebasis nutzen", "Nein, Codes automatisch ableiten"],
        )
        if "Ja" in use_codebase:
            codebase_name = _pick(
                "Welche Codebasis?",
                codebases,
            )
            print(f"  → Codebasis: {codebase_name}")
    else:
        print("\nKeine Codebasen in input/codebases/ gefunden.")
        print("  → Codes werden automatisch abgeleitet (induktiv)")

    # 4. Schritte
    steps = _pick(
        "Welche Schritte ausführen?",
        [
            "Alle Schritte (Analyse + Codebook + QDPX + Auswertung)",
            "Nur KI-Analyse (Schritt 1)",
            "Nur Export (Schritte 2-4, benötigt vorhandene Analyse)",
        ],
    )

    run_analysis = True
    run_export = True
    if "Nur KI" in steps:
        run_export = False
    elif "Nur Export" in steps:
        run_analysis = False

    print("\n" + "=" * 60)
    print("  Konfiguration abgeschlossen – starte Analyse...")
    print("=" * 60)

    return {
        "transcripts": selected_transcripts,
        "recipe_id": recipe_id,
        "codebase_name": codebase_name,
        "run_analysis": run_analysis,
        "run_export": run_export,
    }
