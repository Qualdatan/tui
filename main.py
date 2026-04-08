#!/usr/bin/env python3
"""
Qualitative Analyse-Pipeline.

Interaktiver Modus (Standard):
  python3 main.py

Flag-Modus:
  python3 main.py --recipe mayring
  python3 main.py --recipe mayring --codebase mein_codeset
  python3 main.py --skip-analysis
  python3 main.py --step 1
  python3 main.py --step 2

API-Key wird aus .env geladen (ANTHROPIC_API_KEY).
"""

import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import (
    ANALYSIS_JSON, OUTPUT_DIR, TRANSCRIPTS_DIR, DEFAULT_RECIPE,
)
from src.models import AnalysisResult
from src.recipe import load_recipe, load_codebase, list_recipes
from src.step1_analyze import run_analysis, read_transcripts
from src.step2_codebook import generate_codebook
from src.step3_qdpx import generate_qdpx
from src.step4_evaluation import generate_evaluation


def load_existing_result() -> AnalysisResult:
    """Lädt vorhandene Ergebnisse und liest Dokument-Texte nach."""
    if not ANALYSIS_JSON.exists():
        print(f"FEHLER: {ANALYSIS_JSON} nicht gefunden.")
        print("Bitte erst Schritt 1 ausführen (python3 main.py --step 1)")
        sys.exit(1)
    print(f"Lade vorhandene Analyse: {ANALYSIS_JSON}")
    result = AnalysisResult.load(ANALYSIS_JSON)
    result.documents = read_transcripts()
    return result


def run_export_steps(result: AnalysisResult):
    """Führt Schritte 2-4 aus."""
    print("\n>>> Schritt 2: Codebook generieren")
    generate_codebook(result)

    print("\n>>> Schritt 3: REFI-QDA .qdpx generieren")
    generate_qdpx(result)

    print("\n>>> Schritt 4: Auswertungs-Excel generieren")
    generate_evaluation(result)


def run_interactive():
    """Interaktiver Modus mit CLI-Auswahl."""
    from src.cli import interactive_setup

    config = interactive_setup()

    recipe = load_recipe(config["recipe_id"])

    codebase = ""
    if config["codebase_name"]:
        codebase = load_codebase(config["codebase_name"])
        print(f"  Codebasis geladen: {len(codebase)} Zeichen")

    if config["run_analysis"]:
        print("\n>>> Schritt 1: KI-Analyse der Transkripte")
        result = run_analysis(recipe, TRANSCRIPTS_DIR, codebase)
    else:
        result = load_existing_result()
        # Kategorien aus Recipe nachladen falls fehlend
        if not result.categories:
            result.categories = recipe.categories

    if config["run_export"]:
        run_export_steps(result)

    print("\n" + "=" * 60)
    print(f"  Fertig! Alle Ausgaben in: {OUTPUT_DIR}")
    print("=" * 60)


def run_flagged(args):
    """Flag-basierter Modus."""
    recipe = load_recipe(args.recipe)

    codebase = ""
    if args.codebase:
        codebase = load_codebase(args.codebase)
        print(f"  Codebasis geladen: {len(codebase)} Zeichen")

    print("=" * 60)
    print(f"  Qualitative Analyse – Methode: {recipe.name}")
    print("=" * 60)

    if args.step:
        if args.step == 1:
            print("\n>>> Schritt 1: KI-Analyse der Transkripte")
            run_analysis(recipe, TRANSCRIPTS_DIR, codebase)
        elif args.step in (2, 3, 4):
            result = load_existing_result()
            if not result.categories:
                result.categories = recipe.categories
            if args.step == 2:
                print("\n>>> Schritt 2: Codebook generieren")
                generate_codebook(result)
            elif args.step == 3:
                print("\n>>> Schritt 3: REFI-QDA .qdpx generieren")
                generate_qdpx(result)
            elif args.step == 4:
                print("\n>>> Schritt 4: Auswertungs-Excel generieren")
                generate_evaluation(result)
    else:
        if not args.skip_analysis:
            print("\n>>> Schritt 1: KI-Analyse der Transkripte")
            result = run_analysis(recipe, TRANSCRIPTS_DIR, codebase)
        else:
            result = load_existing_result()
            if not result.categories:
                result.categories = recipe.categories

        run_export_steps(result)

    print("\n" + "=" * 60)
    print(f"  Fertig! Alle Ausgaben in: {OUTPUT_DIR}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Qualitative Analyse-Pipeline",
        epilog="Ohne Flags startet der interaktive Modus.",
    )
    parser.add_argument(
        "--recipe", type=str, default=None,
        help=f"Analyse-Methode (default: {DEFAULT_RECIPE}). Verfügbar: "
             + ", ".join(r["id"] for r in list_recipes()),
    )
    parser.add_argument(
        "--codebase", type=str, default=None,
        help="Name der Codebasis aus input/codebases/",
    )
    parser.add_argument(
        "--skip-analysis", action="store_true",
        help="Überspringe KI-Analyse, nutze vorhandenes JSON",
    )
    parser.add_argument(
        "--step", type=int, choices=[1, 2, 3, 4],
        help="Nur einen bestimmten Schritt ausführen",
    )
    args = parser.parse_args()

    # Wenn irgendein Flag gesetzt → Flag-Modus
    has_flags = args.recipe or args.codebase or args.skip_analysis or args.step
    if has_flags:
        if not args.recipe:
            args.recipe = DEFAULT_RECIPE
        run_flagged(args)
    else:
        run_interactive()


if __name__ == "__main__":
    main()
