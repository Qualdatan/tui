"""Interaktives CLI für die Analyse-Pipeline."""

import sys
from pathlib import Path

from .config import TRANSCRIPTS_DIR, CODEBASES_DIR, DEFAULT_RECIPE
from .recipe import list_recipes, list_codebases
from .run_context import find_interrupted_runs


def _pick(prompt: str, options: list[str], allow_skip: bool = False) -> str | None:
    """Zeigt eine nummerierte Auswahl und gibt die Wahl zurück."""
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")
    if allow_skip:
        print(f"  [0] Ueberspringen")

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
        print("  Ungueltige Auswahl, bitte erneut versuchen.")


def _pick_multiple(prompt: str, options: list[str]) -> list[str]:
    """Zeigt eine nummerierte Auswahl, erlaubt Mehrfachauswahl oder 'alle'."""
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")
    print(f"  [a] Alle auswaehlen")

    while True:
        try:
            choice = input("\nAuswahl (Nummern kommagetrennt, oder 'a' fuer alle): ").strip()
            if choice.lower() == "a":
                return options
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
            selected = [options[i] for i in indices if 0 <= i < len(options)]
            if selected:
                return selected
        except (ValueError, EOFError, IndexError):
            pass
        print("  Ungueltige Auswahl, bitte erneut versuchen.")


def _confirm(prompt: str) -> bool:
    """Ja/Nein-Frage."""
    while True:
        choice = input(f"\n{prompt} [j/n]: ").strip().lower()
        if choice in ("j", "ja", "y", "yes"):
            return True
        if choice in ("n", "nein", "no"):
            return False


def check_interrupted_runs() -> dict | None:
    """Prueft auf unterbrochene Runs und bietet Wiederaufnahme an."""
    interrupted = find_interrupted_runs()
    if not interrupted:
        return None

    print("\n" + "=" * 60)
    print("  Unterbrochene Runs gefunden!")
    print("=" * 60)

    for i, ctx in enumerate(interrupted):
        state = ctx.get_state()
        done = len(state.get("completed_transcripts", []))
        total = len(state.get("transcripts", []))
        steps = state.get("steps_completed", [])
        recipe = state.get("recipe_id", "?")
        started = state.get("started_at", "?")[:19]
        print(f"\n  [{i+1}] {ctx.run_dir.name}")
        print(f"      Recipe: {recipe} | Transkripte: {done}/{total} | Schritte: {steps}")
        print(f"      Gestartet: {started}")

        pending = ctx.get_pending_transcripts()
        if pending:
            print(f"      Ausstehend: {', '.join(pending)}")

        missing_steps = []
        if 1 not in steps:
            missing_steps.append("1 (KI-Analyse)")
        if 2 not in steps:
            missing_steps.append("2 (Codebook)")
        if 3 not in steps:
            missing_steps.append("3 (QDPX)")
        if 4 not in steps:
            missing_steps.append("4 (Auswertung)")
        if missing_steps:
            print(f"      Fehlende Schritte: {', '.join(missing_steps)}")

    options = [f"Fortsetzen: {ctx.run_dir.name}" for ctx in interrupted]
    options.append("Neuen Run starten")

    choice = _pick("Was moechtest du tun?", options)

    if "Neuen Run" in choice:
        return None

    idx = options.index(choice)
    ctx = interrupted[idx]
    state = ctx.get_state()

    return {
        "resume": True,
        "run_dir": ctx.run_dir,
        "recipe_id": state.get("recipe_id", DEFAULT_RECIPE),
        "codebase_name": state.get("codebase_name"),
        "transcripts": state.get("transcripts", []),
    }


def interactive_setup() -> dict:
    """Fuehrt den interaktiven Setup-Dialog und gibt die Konfiguration zurueck."""
    # Zuerst: unterbrochene Runs pruefen
    resume = check_interrupted_runs()
    if resume:
        return resume

    print("\n" + "=" * 60)
    print("  Qualitative Analyse – Neue Analyse")
    print("=" * 60)

    # 1. Transkripte auswaehlen
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
    print(f"  -> {len(selected_transcripts)} Transkript(e) ausgewaehlt")

    # 2. Methode (Recipe) auswaehlen
    recipes = list_recipes()
    if not recipes:
        print(f"\nKeine Recipes gefunden. Bitte pruefe den Ordner 'recipes/'.")
        sys.exit(1)

    recipe_names = [f"{r['id']} – {r['name']}" for r in recipes]
    recipe_choice = _pick("Welche Analyse-Methode?", recipe_names)
    recipe_id = recipe_choice.split(" – ")[0]
    print(f"  -> Methode: {recipe_id}")

    # 3. Codebasis?
    codebases = list_codebases()
    codebase_name = None
    if codebases:
        use_codebase = _pick(
            "Moechtest du eine vorhandene Codebasis verwenden?",
            ["Ja, vorhandene Codebasis nutzen", "Nein, Codes automatisch ableiten"],
        )
        if "Ja" in use_codebase:
            codebase_name = _pick("Welche Codebasis?", codebases)
            print(f"  -> Codebasis: {codebase_name}")
    else:
        print("\nKeine Codebasen in input/codebases/ gefunden.")
        print("  -> Codes werden automatisch abgeleitet (induktiv)")

    print("\n" + "=" * 60)
    print("  Konfiguration abgeschlossen – starte Analyse...")
    print("=" * 60)

    return {
        "resume": False,
        "transcripts": selected_transcripts,
        "recipe_id": recipe_id,
        "codebase_name": codebase_name,
    }
