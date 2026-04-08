#!/usr/bin/env python3
"""
Qualitative Inhaltsanalyse nach Mayring – Hauptprogramm.

Analysiert Interviewtranskripte (.docx) via Claude API und generiert:
  1. analysis_results.json  – Strukturierte Analyse-Ergebnisse
  2. codebook.xlsx          – Codebook mit Definitionen
  3. project.qdpx           – REFI-QDA Projektdatei für MAXQDA 2024
  4. auswertung.xlsx        – Auswertung (3 Sheets)

Verwendung:
  python main.py                    # Alle 4 Schritte
  python main.py --skip-analysis    # Schritte 2-4 mit vorhandenem JSON
  python main.py --step 1           # Nur Schritt 1
  python main.py --step 2           # Nur Schritt 2
  python main.py --step 3           # Nur Schritt 3
  python main.py --step 4           # Nur Schritt 4

API-Key wird aus .env geladen (ANTHROPIC_API_KEY).
"""

import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# Projektroot zum Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import ANALYSIS_JSON, OUTPUT_DIR
from src.models import AnalysisResult
from src.step1_analyze import run_analysis, read_transcripts
from src.step2_codebook import generate_codebook
from src.step3_qdpx import generate_qdpx
from src.step4_evaluation import generate_evaluation


def load_or_run_analysis(skip_analysis: bool) -> AnalysisResult:
    """Lädt vorhandene Ergebnisse oder führt die Analyse durch."""
    if skip_analysis:
        if not ANALYSIS_JSON.exists():
            print(f"FEHLER: {ANALYSIS_JSON} nicht gefunden. Bitte erst Schritt 1 ausführen.")
            sys.exit(1)
        print(f"Lade vorhandene Analyse: {ANALYSIS_JSON}")
        result = AnalysisResult.load(ANALYSIS_JSON)
        # Dokument-Texte nachladen (werden für QDPX benötigt)
        result.documents = read_transcripts()
        return result
    else:
        return run_analysis()


def main():
    parser = argparse.ArgumentParser(
        description="Qualitative Inhaltsanalyse nach Mayring"
    )
    parser.add_argument(
        "--skip-analysis", action="store_true",
        help="Überspringe KI-Analyse, nutze vorhandenes JSON"
    )
    parser.add_argument(
        "--step", type=int, choices=[1, 2, 3, 4],
        help="Nur einen bestimmten Schritt ausführen"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Qualitative Inhaltsanalyse nach Mayring")
    print("=" * 60)

    if args.step:
        # Einzelner Schritt
        if args.step == 1:
            print("\n>>> Schritt 1: KI-Analyse der Transkripte")
            run_analysis()
        elif args.step in (2, 3, 4):
            result = load_or_run_analysis(skip_analysis=True)
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
        # Alle Schritte
        skip = args.skip_analysis

        if not skip:
            print("\n>>> Schritt 1: KI-Analyse der Transkripte")
            result = run_analysis()
        else:
            result = load_or_run_analysis(skip_analysis=True)

        print("\n>>> Schritt 2: Codebook generieren")
        generate_codebook(result)

        print("\n>>> Schritt 3: REFI-QDA .qdpx generieren")
        generate_qdpx(result)

        print("\n>>> Schritt 4: Auswertungs-Excel generieren")
        generate_evaluation(result)

    print("\n" + "=" * 60)
    print(f"  Fertig! Alle Ausgaben in: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
