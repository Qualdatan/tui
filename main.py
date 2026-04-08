#!/usr/bin/env python3
"""
Qualitative Analyse-Pipeline.

Interaktiver Modus (Standard):
  python3 main.py

Flag-Modus:
  python3 main.py --recipe mayring
  python3 main.py --recipe mayring --codebase mein_codeset
  python3 main.py --resume
  python3 main.py --step 2

API-Key und Modell-Overrides in .env (siehe .env.example).
"""

import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import TRANSCRIPTS_DIR, DEFAULT_RECIPE
from src.models import AnalysisResult
from src.recipe import load_recipe, load_codebase, list_recipes
from src.step1_analyze import run_analysis, read_transcripts
from src.step2_codebook import generate_codebook
from src.step3_qdpx import generate_qdpx
from src.step4_evaluation import generate_evaluation
from src.run_context import (
    RunContext, create_run, find_interrupted_runs, resume_run,
)


def load_existing_result(ctx: RunContext) -> AnalysisResult:
    """Laedt vorhandene Ergebnisse und liest Dokument-Texte nach."""
    if not ctx.analysis_json.exists():
        print(f"FEHLER: {ctx.analysis_json} nicht gefunden.")
        print("Bitte erst Schritt 1 ausfuehren.")
        sys.exit(1)
    print(f"Lade vorhandene Analyse: {ctx.analysis_json}")
    result = AnalysisResult.load(ctx.analysis_json)
    result.documents = read_transcripts()
    return result


def run_export_steps(result: AnalysisResult, ctx: RunContext):
    """Fuehrt Schritte 2-4 aus."""
    if not ctx.is_step_done(2):
        print("\n>>> Schritt 2: Codebook generieren")
        generate_codebook(result, ctx.codebook_xlsx)
        ctx.mark_step_done(2)
    else:
        print("\n>>> Schritt 2: Codebook (bereits erledigt)")

    if not ctx.is_step_done(3):
        print("\n>>> Schritt 3: REFI-QDA .qdpx generieren")
        generate_qdpx(result, ctx.qdpx_file)
        ctx.mark_step_done(3)
    else:
        print("\n>>> Schritt 3: QDPX (bereits erledigt)")

    if not ctx.is_step_done(4):
        print("\n>>> Schritt 4: Auswertungs-Excel generieren")
        generate_evaluation(result, ctx.evaluation_xlsx)
        ctx.mark_step_done(4)
    else:
        print("\n>>> Schritt 4: Auswertung (bereits erledigt)")


def run_pipeline(ctx: RunContext, recipe_id: str,
                 codebase_name: str | None = None,
                 step: int | None = None,
                 skip_analysis: bool = False):
    """Fuehrt die Pipeline mit einem RunContext aus."""
    recipe = load_recipe(recipe_id)

    codebase = ""
    if codebase_name:
        codebase = load_codebase(codebase_name)
        print(f"  Codebasis geladen: {len(codebase)} Zeichen")

    print("=" * 60)
    print(f"  Qualitative Analyse – {recipe.name}")
    print(f"  Run: {ctx.run_dir.name}")
    print("=" * 60)

    if step:
        # Einzelner Schritt
        if step == 1:
            print("\n>>> Schritt 1: KI-Analyse der Transkripte")
            run_analysis(recipe, ctx, TRANSCRIPTS_DIR, codebase)
        elif step in (2, 3, 4):
            result = load_existing_result(ctx)
            if not result.categories:
                result.categories = recipe.categories
            if step == 2:
                print("\n>>> Schritt 2: Codebook generieren")
                generate_codebook(result, ctx.codebook_xlsx)
                ctx.mark_step_done(2)
            elif step == 3:
                print("\n>>> Schritt 3: REFI-QDA .qdpx generieren")
                generate_qdpx(result, ctx.qdpx_file)
                ctx.mark_step_done(3)
            elif step == 4:
                print("\n>>> Schritt 4: Auswertungs-Excel generieren")
                generate_evaluation(result, ctx.evaluation_xlsx)
                ctx.mark_step_done(4)
    else:
        # Alle Schritte
        if not skip_analysis and not ctx.is_step_done(1):
            print("\n>>> Schritt 1: KI-Analyse der Transkripte")
            result = run_analysis(recipe, ctx, TRANSCRIPTS_DIR, codebase)
        else:
            result = load_existing_result(ctx)
            if not result.categories:
                result.categories = recipe.categories

        run_export_steps(result, ctx)

    ctx.mark_completed()
    print("\n" + "=" * 60)
    print(f"  Fertig! Ergebnisse in: {ctx.run_dir}")
    print("=" * 60)


def run_interactive():
    """Interaktiver Modus mit CLI-Auswahl."""
    from src.cli import interactive_setup

    config = interactive_setup()

    if config.get("resume"):
        # Unterbrochenen Run fortsetzen
        ctx = resume_run(config["run_dir"])
        print(f"\n  Setze Run fort: {ctx.run_dir.name}")
        run_pipeline(ctx, config["recipe_id"], config.get("codebase_name"))
    else:
        # Neuer Run
        ctx = create_run()
        ctx.init_state(
            recipe_id=config["recipe_id"],
            codebase_name=config.get("codebase_name"),
            transcripts=config["transcripts"],
        )
        run_pipeline(ctx, config["recipe_id"], config.get("codebase_name"))


def run_flagged(args):
    """Flag-basierter Modus."""
    if args.resume:
        # Letzten unterbrochenen Run fortsetzen
        interrupted = find_interrupted_runs()
        if not interrupted:
            print("Kein unterbrochener Run gefunden.")
            sys.exit(1)
        ctx = resume_run(interrupted[0].run_dir)
        state = ctx.get_state()
        recipe_id = state.get("recipe_id", args.recipe)
        codebase_name = state.get("codebase_name", args.codebase)
        print(f"Setze Run fort: {ctx.run_dir.name}")
        run_pipeline(ctx, recipe_id, codebase_name, args.step, args.skip_analysis)
    else:
        # Neuer Run
        ctx = create_run()
        transcripts = sorted(f.name for f in TRANSCRIPTS_DIR.glob("*.docx"))
        ctx.init_state(
            recipe_id=args.recipe,
            codebase_name=args.codebase,
            transcripts=transcripts,
        )
        run_pipeline(ctx, args.recipe, args.codebase, args.step, args.skip_analysis)


def main():
    parser = argparse.ArgumentParser(
        description="Qualitative Analyse-Pipeline",
        epilog="Ohne Flags startet der interaktive Modus.",
    )
    parser.add_argument(
        "--recipe", type=str, default=None,
        help=f"Analyse-Methode (default: {DEFAULT_RECIPE}). Verfuegbar: "
             + ", ".join(r["id"] for r in list_recipes()),
    )
    parser.add_argument(
        "--codebase", type=str, default=None,
        help="Name der Codebasis aus input/codebases/",
    )
    parser.add_argument(
        "--skip-analysis", action="store_true",
        help="Ueberspringe KI-Analyse, nutze vorhandenes JSON",
    )
    parser.add_argument(
        "--step", type=int, choices=[1, 2, 3, 4],
        help="Nur einen bestimmten Schritt ausfuehren",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Letzten unterbrochenen Run fortsetzen",
    )
    args = parser.parse_args()

    has_flags = args.recipe or args.codebase or args.skip_analysis or args.step or args.resume
    if has_flags:
        if not args.recipe and not args.resume:
            args.recipe = DEFAULT_RECIPE
        run_flagged(args)
    else:
        run_interactive()


if __name__ == "__main__":
    main()
