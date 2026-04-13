#!/usr/bin/env python3
"""
Simple BIM — Qualitative Analyse-Pipeline.

Usage:

    python main.py                          # interaktiver Modus (farbiges CLI)
    python main.py transcripts [--recipe mayring] [--codebase X] [...]
    python main.py documents   [--project HKS] [--recipe pdf_analyse] [...]
    python main.py company     [HKS] [PBN] [--all] [--codebase X] [...]
    python main.py testrun     [boe|company|plans]    # vordefinierte Testruns
    python main.py curate      [--company HKS] [--from interviews|documents]
    python main.py triangulate [--company HKS] [--rebuild] [--run-dir PATH]
    python main.py resume

API-Key und Modell-Overrides in .env (siehe .env.example).
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# Nur leichtgewichtige Imports auf Top-Level -- schwere Module (anthropic,
# openpyxl, pymupdf) werden erst in den jeweiligen cmd_*-Funktionen geladen.
# Das Package ist via `pip install -e .` als `src` importierbar.
from src.config import (
    TRANSCRIPTS_DIR, COMPANIES_DIR, DEFAULT_RECIPE,
)
from src.recipe import load_recipe, load_codebase, parse_codebase_yaml, CODING_STRATEGIES
from src.run_context import (
    RunContext, create_run, find_interrupted_runs, resume_run,
)
from src.cli import (
    console, print_header, print_step, print_success, print_warning,
    print_error, print_summary, spinner,
)
from src.testruns import list_profiles, get_profile, build_pdf_list as build_testrun_pdfs


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DEFAULT_DOCUMENTS_RECIPE = "pdf_analyse"
DEFAULT_INTERVIEW_RECIPE = DEFAULT_RECIPE  # 'mayring' per default


def _apply_coding_strategy_override(recipe, coding_strategy: str | None):
    """Liefert eine Kopie von ``recipe`` mit ueberschriebener coding_strategy.

    Wenn ``coding_strategy`` None ist, wird das Recipe unveraendert
    zurueckgegeben. Recipe ist ein Dataclass — wir nutzen
    ``dataclasses.replace`` fuer eine saubere Kopie.
    """
    if coding_strategy is None:
        return recipe
    if coding_strategy not in CODING_STRATEGIES:
        raise ValueError(
            f"Ungueltige coding_strategy '{coding_strategy}'. "
            f"Erlaubt: {CODING_STRATEGIES}"
        )
    return dataclasses.replace(recipe, coding_strategy=coding_strategy)


def load_existing_result(ctx: RunContext):
    """Laedt vorhandene Ergebnisse und liest Dokument-Texte nach."""
    from src.models import AnalysisResult
    from src.step1_analyze import read_transcripts

    if not ctx.analysis_json.exists():
        print(f"FEHLER: {ctx.analysis_json} nicht gefunden.")
        print("Bitte erst Schritt 1 ausfuehren.")
        sys.exit(1)
    print(f"Lade vorhandene Analyse: {ctx.analysis_json}")
    result = AnalysisResult.load(ctx.analysis_json)
    result.documents = read_transcripts()
    return result


def run_export_steps(result, ctx: RunContext,
                     qdpx_path: Path | None = None,
                     codebase_codes: dict | None = None,
                     codebase_name: str | None = None):
    """Fuehrt Schritte 2-4 aus."""
    from src.step2_codebook import generate_codebook
    from src.step3_qdpx import generate_qdpx
    from src.step4_evaluation import generate_evaluation

    if not ctx.is_step_done(2):
        print("\n>>> Schritt 2: Codebook generieren")
        generate_codebook(result, ctx.codebook_xlsx)
        ctx.mark_step_done(2)
    else:
        print("\n>>> Schritt 2: Codebook (bereits erledigt)")

    if not ctx.is_step_done(3):
        print("\n>>> Schritt 3: REFI-QDA .qdpx generieren")
        target = qdpx_path or ctx.qdpx_file
        target.parent.mkdir(parents=True, exist_ok=True)
        generate_qdpx(
            result, target,
            codebase_codes=codebase_codes,
            codebase_name=codebase_name,
        )
        ctx.mark_step_done(3)
    else:
        print("\n>>> Schritt 3: QDPX (bereits erledigt)")

    if not ctx.is_step_done(4):
        print("\n>>> Schritt 4: Auswertungs-Excel generieren")
        generate_evaluation(result, ctx.evaluation_xlsx)
        ctx.mark_step_done(4)
    else:
        print("\n>>> Schritt 4: Auswertung (bereits erledigt)")


# ---------------------------------------------------------------------------
# Transcripts flow (Legacy Interview-Pipeline)
# ---------------------------------------------------------------------------

def run_transcripts_pipeline(ctx: RunContext, recipe_id: str,
                             codebase_name: str | None = None,
                             coding_strategy: str | None = None,
                             step: int | None = None,
                             skip_analysis: bool = False,
                             transcripts_dir: Path | None = None,
                             qdpx_path: Path | None = None):
    """Fuehrt die klassische Interview-Pipeline mit einem RunContext aus."""
    from src.step1_analyze import run_analysis
    from src.step2_codebook import generate_codebook
    from src.step3_qdpx import generate_qdpx
    from src.step4_evaluation import generate_evaluation

    recipe = load_recipe(recipe_id)
    recipe = _apply_coding_strategy_override(recipe, coding_strategy)

    codebase = ""
    codebase_codes: dict | None = None
    if codebase_name:
        codebase = load_codebase(codebase_name)
        print(f"  Codebasis geladen: {len(codebase)} Zeichen")
        try:
            codebase_codes = parse_codebase_yaml(codebase_name) or None
            if codebase_codes:
                print(f"  Codebasis geparst: {len(codebase_codes)} Codes")
        except Exception as e:
            print(f"  WARN: Codebasis konnte nicht strukturiert geparst werden: {e}")
            codebase_codes = None

    source_dir = transcripts_dir or TRANSCRIPTS_DIR

    print("=" * 60)
    print(f"  Qualitative Analyse – {recipe.name}")
    print(f"  Run: {ctx.run_dir.name}")
    print(f"  Coding-Strategy: {recipe.coding_strategy}")
    print("=" * 60)

    if step:
        if step == 1:
            print("\n>>> Schritt 1: KI-Analyse der Transkripte")
            run_analysis(recipe, ctx, source_dir, codebase)
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
                target = qdpx_path or ctx.qdpx_file
                target.parent.mkdir(parents=True, exist_ok=True)
                generate_qdpx(
                    result, target,
                    codebase_codes=codebase_codes,
                    codebase_name=codebase_name,
                )
                ctx.mark_step_done(3)
            elif step == 4:
                print("\n>>> Schritt 4: Auswertungs-Excel generieren")
                generate_evaluation(result, ctx.evaluation_xlsx)
                ctx.mark_step_done(4)
    else:
        if not skip_analysis and not ctx.is_step_done(1):
            print("\n>>> Schritt 1: KI-Analyse der Transkripte")
            result = run_analysis(recipe, ctx, source_dir, codebase)
        else:
            result = load_existing_result(ctx)
            if not result.categories:
                result.categories = recipe.categories

        run_export_steps(
            result, ctx, qdpx_path=qdpx_path,
            codebase_codes=codebase_codes,
            codebase_name=codebase_name,
        )

    # Pivot-Export (wide-format Excel fuer Pivot-Tabellen)
    try:
        from src.pivot_export import build_pivot_excel
        build_pivot_excel(
            ctx, ctx.run_dir / "pivot_results.xlsx",
            codebase_codes=codebase_codes,
        )
    except Exception as e:
        print(f"  WARN: Pivot-Export fehlgeschlagen: {e}")

    ctx.mark_completed()
    print("\n" + "=" * 60)
    print(f"  Fertig! Ergebnisse in: {ctx.run_dir}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Interactive entry point
# ---------------------------------------------------------------------------

def run_interactive():
    """Interaktiver Modus mit farbigem CLI."""
    from src.cli import (
        _pick, pick_companies, pick_recipe, pick_recipe_pair, pick_codebook,
        check_interrupted_runs, _pick_multiple,
    )

    print_header("Simple BIM Pipeline", "Qualitative Analyse fuer Bauprojekte")

    # Unterbrochene Runs pruefen
    resume_info = check_interrupted_runs()
    if resume_info:
        ctx = resume_run(resume_info["run_dir"])
        print_success(f"Setze Run fort: {ctx.run_dir.name}")
        run_transcripts_pipeline(
            ctx, resume_info["recipe_id"], resume_info.get("codebase_name"),
        )
        return

    # Hauptmenue
    modes = [
        "\U0001f3e2 Company-Analyse -- Interviews + Projektdokumente trianguliert",
        "\U0001f399\ufe0f  Interview-Analyse -- Transkripte kodieren (Mayring etc.)",
        "\U0001f4c4 Dokument-Analyse -- PDFs analysieren und kodieren",
        "\U0001f9ea Testrun -- Vordefinierte Testruns mit Beispieldaten",
        "\U0001f4d6 Codebook-Curation -- Draft-Codebook aus Sample bootstrappen",
    ]
    choice = _pick("Was moechtest du tun?", modes)
    if choice is None:
        return

    if "Company" in choice:
        from src.company_scanner import list_companies
        if COMPANIES_DIR.exists() and list_companies():
            companies = pick_companies()
            if not companies:
                print_warning("Keine Auswahl -- Abbruch.")
                return
            iv_recipe, doc_recipe = pick_recipe_pair()
            codebase_name, coding_strategy = pick_codebook()
            args = argparse.Namespace(
                companies=companies, all=False,
                recipe_interviews=iv_recipe, recipe_documents=doc_recipe,
                codebase=codebase_name, coding_strategy=coding_strategy,
                skip_plans=False, skip_pattern=[], project=[],
                no_convert_office=False, no_triangulate=False,
            )
            cmd_company(args)
        else:
            print_warning("Keine Companies gefunden. Bitte Companies in input/companies/ anlegen.")

    elif "Interview" in choice:
        transcripts = sorted(f.name for f in TRANSCRIPTS_DIR.glob("*.docx"))
        if not transcripts:
            print_error(f"Keine .docx-Dateien in {TRANSCRIPTS_DIR} gefunden.")
            return
        selected = _pick_multiple(
            "Welche Transkripte sollen analysiert werden?", transcripts,
        )
        recipe_id = pick_recipe(category="interviewanalysis", default_id="mayring")
        codebase_name, coding_strategy = pick_codebook()

        ctx = create_run()
        ctx.init_state(
            recipe_id=recipe_id, codebase_name=codebase_name,
            transcripts=selected,
        )
        run_transcripts_pipeline(
            ctx, recipe_id, codebase_name=codebase_name,
            coding_strategy=coding_strategy,
        )

    elif "Dokument" in choice:
        recipe_id = pick_recipe(category="documentanalysis", default_id="pdf_analyse")
        codebase_name, coding_strategy = pick_codebook()
        args = argparse.Namespace(
            project=None, recipe=recipe_id, qdpx=None,
            step=None, mode=None, classify_mode="local",
            coding_strategy=coding_strategy, skip_plans=False,
            skip_pattern=[], no_convert_office=False,
        )
        cmd_documents(args)

    elif "Testrun" in choice:
        args = argparse.Namespace(
            profile=None, recipe=None, codebase=None, resume=False,
        )
        cmd_testrun(args)

    elif "Codebook" in choice:
        args = argparse.Namespace(
            company=None, from_source="interviews", codebase=None,
            sample_size=4, recipe=None, coding_strategy=None,
        )
        cmd_curate(args)


# ---------------------------------------------------------------------------
# cmd_transcripts
# ---------------------------------------------------------------------------

def cmd_transcripts(args):
    """Interview-Pipeline (legacy flow)."""
    recipe_id = args.recipe or DEFAULT_INTERVIEW_RECIPE

    ctx = create_run()
    transcripts = sorted(f.name for f in TRANSCRIPTS_DIR.glob("*.docx"))
    ctx.init_state(
        recipe_id=recipe_id,
        codebase_name=args.codebase,
        transcripts=transcripts,
        mode="transcripts",
    )
    run_transcripts_pipeline(
        ctx, recipe_id,
        codebase_name=args.codebase,
        coding_strategy=args.coding_strategy,
        step=args.step,
        skip_analysis=args.skip_analysis,
    )


# ---------------------------------------------------------------------------
# cmd_documents
# ---------------------------------------------------------------------------

def cmd_documents(args):
    """PDF-/Dokument-Analyse (delegiert an pdf_coder.run_pipeline)."""
    with spinner("Pipeline-Module laden...", phase="scan"):
        from src.pdf_coder import run_pipeline as run_pdf_pipeline

    recipe_id = args.recipe or DEFAULT_DOCUMENTS_RECIPE
    qdpx_path = Path(args.qdpx) if getattr(args, "qdpx", None) else None

    ctx = create_run()
    ctx.init_state(
        recipe_id=recipe_id,
        codebase_name=None,
        transcripts=[],
        mode="documents",
    )

    if args.coding_strategy:
        ctx.db.set_state("coding_strategy_override", args.coding_strategy)

    run_pdf_pipeline(
        ctx,
        recipe_id=recipe_id,
        project_filter=args.project,
        qdpx_path=qdpx_path,
        step=args.step,
        mode=args.mode,
        classify_mode=args.classify_mode,
        skip_plans=args.skip_plans,
        skip_patterns=args.skip_pattern or None,
        convert_office=not args.no_convert_office,
    )


# ---------------------------------------------------------------------------
# cmd_company — neuer Orchestrator
# ---------------------------------------------------------------------------

def _run_interview_flow_for_company(ctx, company, company_id: int,
                                    recipe_id: str,
                                    codebase_name: str | None,
                                    coding_strategy: str | None):
    """Laesst die Interview-Pipeline auf ``company.interviews`` laufen.

    Das Verzeichnis mit den Interview-Dateien wird direkt an
    ``run_analysis(source_dir=...)`` weitergereicht — step1_analyze
    unterstuetzt das bereits. Das QDPX wird unter
    ``<run>/<company>/qda/interviews.qdpx`` abgelegt.
    """
    from src.step1_analyze import run_analysis
    from src.step3_qdpx import generate_qdpx

    if not company.interviews:
        return

    recipe = load_recipe(recipe_id)
    recipe = _apply_coding_strategy_override(recipe, coding_strategy)

    for iv in company.interviews:
        ctx.db.upsert_interview_doc(
            company_id=company_id,
            filename=iv.name,
            path=str(iv),
        )

    interview_dir = company.interviews[0].parent
    if not all(iv.parent == interview_dir for iv in company.interviews):
        print(f"  WARN: Interviews von {company.name} liegen in verschiedenen "
              f"Ordnern — nutze {interview_dir} als Basis.")

    codebase = ""
    codebase_codes: dict | None = None
    if codebase_name:
        codebase = load_codebase(codebase_name)
        print(f"  Codebasis: {len(codebase)} Zeichen")
        try:
            codebase_codes = parse_codebase_yaml(codebase_name) or None
        except Exception as e:
            print(f"  WARN: Codebasis konnte nicht geparst werden: {e}")
            codebase_codes = None

    print(f"  Analyse-Methode: {recipe.id} (strategy={recipe.coding_strategy})")

    try:
        result = run_analysis(
            recipe, ctx, interview_dir, codebase,
            analysis_json_override=ctx.company_analysis_json(company.name),
            prompts_dir_override=ctx.company_prompts_dir(company.name),
            responses_dir_override=ctx.company_responses_dir(company.name),
        )
    except Exception as e:  # pragma: no cover - defensive
        print(f"  FEHLER bei Interview-Analyse: {e}")
        return

    qdpx_target = ctx.company_qdpx_path(company.name, "interviews.qdpx")
    print(f"  QDPX-Export: {qdpx_target}")
    try:
        generate_qdpx(
            result, qdpx_target,
            codebase_codes=codebase_codes,
            codebase_name=codebase_name,
        )
    except Exception as e:  # pragma: no cover - defensive
        print(f"  FEHLER beim QDPX-Export: {e}")


def _run_pdf_flow_for_source(ctx, company, source_path: Path, source_label: str,
                             company_id: int, project_id: int | None,
                             source_kind: str, args):
    """Gemeinsamer PDF-Flow fuer Projekt- und Sonstiges-Ordner.

    Wraps pdf_coder.run_pipeline und annotiert die Ergebnis-PDFs in
    ``<run>/<company>/annotated/<source_label>/...``. Die Zuordnung
    ``company_id``/``project_id``/``source_kind`` wird direkt nach dem
    Registrieren der PDFs in der DB gesetzt.
    """
    from src import pdf_coder as _pdf_coder_module
    from src.pdf_scanner import scan_projects, filter_pdfs, build_manifest

    recipe_id = args.recipe_documents or DEFAULT_DOCUMENTS_RECIPE

    # Scan: company.path als Basis, project_filter = source_label
    # (d.h. nur den gewuenschten Unterordner). Das ergibt
    # pdf["project"] == source_label.
    convert_office = not args.no_convert_office
    convert_cache = ctx.run_dir / "converted" / company.name / source_label \
        if convert_office else None
    if convert_cache is not None:
        convert_cache.mkdir(parents=True, exist_ok=True)

    try:
        pdfs = scan_projects(
            projects_dir=company.path,
            project_filter=source_label,
            convert_office=convert_office,
            convert_cache_dir=convert_cache,
        )
    except Exception as e:
        print(f"  FEHLER beim Scan: {e}")
        return

    if not pdfs:
        print(f"  Keine PDFs in {source_path}.")
        return

    # Filter (skip-plans / skip-pattern)
    if args.skip_plans or args.skip_pattern:
        before = len(pdfs)
        pdfs, removed = filter_pdfs(
            pdfs,
            skip_plans=args.skip_plans,
            skip_patterns=args.skip_pattern or None,
        )
        if removed:
            print(f"  Filter: {len(removed)}/{before} PDFs entfernt")

    if not pdfs:
        print("  Nach Filtern keine PDFs uebrig.")
        return

    # In DB registrieren und company_id/project_id/source_kind setzen
    pdf_ids = {}
    conn = ctx.db._get_conn()
    for pdf in pdfs:
        file_size = 0
        try:
            file_size = Path(pdf["path"]).stat().st_size // 1024
        except OSError:
            pass
        pid = ctx.db.upsert_pdf(
            project=pdf["project"],
            filename=pdf["filename"],
            relative_path=pdf["relative_path"],
            path=pdf["path"],
            file_size_kb=file_size,
        )
        # company/project/source_kind-Spalten setzen (additive Phase-2-Felder)
        try:
            conn.execute(
                """UPDATE pdf_documents
                   SET company_id = ?, project_id = ?, source_kind = ?
                   WHERE id = ?""",
                (company_id, project_id, source_kind, pid),
            )
            conn.commit()
        except Exception:
            pass  # nullable / Spalten existieren evtl. nicht in Legacy-DBs
        pdf_ids[pdf["relative_path"]] = pid

    manifest = build_manifest(pdfs)
    print(f"  Manifest: {manifest.get('total_pdfs', len(pdfs))} PDFs, "
          f"{manifest.get('total_size_mb', 0):.1f} MB")

    # --- Mini-Pipeline: Extract + Classify + Code + Visual + Annotate ---
    # Wir ruhen uns auf den Einzelfunktionen von pdf_coder aus, damit die
    # Orchestrierung pro Projekt laeuft und wir die annotierten PDFs in
    # den company-spezifischen Ordner schreiben koennen.
    recipe = load_recipe(recipe_id)
    recipe = _apply_coding_strategy_override(recipe, args.coding_strategy)

    try:
        classifications = _pdf_coder_module.run_classification(
            pdfs, ctx, pdf_ids, classify_mode="local",
        )
    except Exception as e:
        print(f"  WARN: Klassifikation fehlgeschlagen: {e}")
        classifications = None

    text_pdfs = pdfs
    visual_pdfs = []
    if classifications:
        from src.pdf_classifier import split_by_type
        groups = split_by_type(pdfs, classifications)
        text_pdfs = groups.get("text", []) + groups.get("mixed", [])
        visual_pdfs = groups.get("plan", []) + groups.get("photo", [])

    extractions = {}
    if text_pdfs:
        try:
            extractions = _pdf_coder_module.run_extraction(text_pdfs, ctx, pdf_ids)
        except Exception as e:
            print(f"  WARN: Extraktion fehlgeschlagen: {e}")

    if text_pdfs and extractions:
        try:
            _pdf_coder_module.run_coding(
                text_pdfs, extractions, recipe, codesystem="",
                ctx=ctx, pdf_ids=pdf_ids,
            )
        except Exception as e:
            print(f"  WARN: Coding fehlgeschlagen: {e}")

    if visual_pdfs:
        try:
            _pdf_coder_module.run_visual(visual_pdfs, ctx, pdf_ids)
        except Exception as e:
            print(f"  WARN: Visual-Pipeline fehlgeschlagen: {e}")

    # Annotation in den company-spezifischen Ordner umleiten per Monkey-Patch
    # auf RunContext.annotated_dir / annotated_path_for.
    original_annotated_dir = RunContext.annotated_dir
    original_annotated_path_for = RunContext.annotated_path_for
    try:
        company_annotated = ctx.company_annotated_dir(company.name)

        def _company_annotated_dir(self):
            return company_annotated

        def _company_annotated_path_for(self, project, relative_path):
            rel = Path(relative_path)
            if project and rel.parts and rel.parts[0] == project:
                target = company_annotated / rel
            elif project:
                target = company_annotated / project / rel
            else:
                target = company_annotated / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            return target

        RunContext.annotated_dir = property(_company_annotated_dir)
        RunContext.annotated_path_for = _company_annotated_path_for

        try:
            _pdf_coder_module.run_annotation(ctx, recipe=recipe)
        except Exception as e:
            print(f"  WARN: Annotation fehlgeschlagen: {e}")
    finally:
        RunContext.annotated_dir = original_annotated_dir
        RunContext.annotated_path_for = original_annotated_path_for


def cmd_company(args):
    """Company-Orchestrator: Interviews + Projektdokumente trianguliert."""
    from src.company_scanner import list_companies, scan_company

    # 1. Auswahl
    if args.all:
        companies = list_companies()
    elif args.companies:
        companies = list(args.companies)
    else:
        from src.cli import pick_companies
        companies = pick_companies()

    if not companies:
        print("Keine Companies ausgewaehlt — Abbruch.")
        sys.exit(1)

    recipe_documents = args.recipe_documents or DEFAULT_DOCUMENTS_RECIPE
    recipe_interviews = args.recipe_interviews or DEFAULT_INTERVIEW_RECIPE

    # 2. Run anlegen
    ctx = create_run()
    ctx.init_state(
        mode="company",
        recipe_id=recipe_documents,
        companies=companies,
        recipe_interviews=recipe_interviews,
        recipe_documents=recipe_documents,
        codebase_name=args.codebase,
        coding_strategy=args.coding_strategy,
    )

    print("=" * 60)
    print("  Simple BIM — Company-Modus")
    print(f"  Run: {ctx.run_dir.name}")
    print(f"  Companies: {', '.join(companies)}")
    if args.project:
        print(f"  Projekt-Filter: {', '.join(args.project)}")
    print("=" * 60)

    # 3. Pro Company die beiden Flows fahren
    for company_name in companies:
        try:
            company = scan_company(company_name)
        except FileNotFoundError as e:
            print(f"  SKIP {company_name}: {e}")
            continue

        company_id = ctx.db.upsert_company(company.name, str(company.path))

        # Pfad A: Interviews
        if company.interviews:
            print(f"\n>>> {company.name}: {len(company.interviews)} Interview(s)")
            _run_interview_flow_for_company(
                ctx, company, company_id,
                recipe_id=recipe_interviews,
                codebase_name=args.codebase,
                coding_strategy=args.coding_strategy,
            )
        else:
            print(f"\n>>> {company.name}: keine Interviews")

        # Pfad B: Projekte (optional gefiltert via --project)
        projects = company.projects
        if args.project:
            project_filter = set(args.project)
            projects = [p for p in projects
                        if p.code in project_filter
                        or p.folder_name in project_filter]
            skipped = len(company.projects) - len(projects)
            if skipped:
                print(f"  ({skipped} Projekt(e) per --project uebersprungen)")
        for project in projects:
            print(f"\n>>> {company.name} / {project.folder_name}: "
                  f"{project.pdf_count} PDFs, {project.office_count} Office-Files")
            project_id = ctx.db.upsert_project(
                company_id=company_id,
                folder_name=project.folder_name,
                code=project.code,
                name=project.name,
                source_dir=str(project.path),
            )
            _run_pdf_flow_for_source(
                ctx, company,
                source_path=project.path,
                source_label=project.folder_name,
                company_id=company_id,
                project_id=project_id,
                source_kind="project",
                args=args,
            )

        # Pfad B (special): Sonstiges
        if company.sonstiges_path and company.sonstiges_files:
            print(f"\n>>> {company.name} / Sonstiges: "
                  f"{len(company.sonstiges_files)} File(s)")
            _run_pdf_flow_for_source(
                ctx, company,
                source_path=company.sonstiges_path,
                source_label=company.sonstiges_path.name,
                company_id=company_id,
                project_id=None,
                source_kind="sonstiges",
                args=args,
            )

    # 4. Triangulator updaten
    if not args.no_triangulate:
        try:
            from src.triangulator import update_from_run
            stats = update_from_run(ctx.run_dir, mode="company")
            print(f"\nTriangulations-DB aktualisiert: {stats}")
        except Exception as e:
            print(f"\nWARN: Triangulations-Update fehlgeschlagen: {e}")

    # 5. Pivot-Export (wide-format Excel fuer Pivot-Tabellen)
    try:
        from src.pivot_export import build_pivot_excel
        cb_codes = None
        if args.codebase:
            try:
                cb_codes = parse_codebase_yaml(args.codebase) or None
            except Exception:
                cb_codes = None
        build_pivot_excel(
            ctx, ctx.run_dir / "pivot_results.xlsx",
            codebase_codes=cb_codes,
        )
    except Exception as e:
        print(f"\nWARN: Pivot-Export fehlgeschlagen: {e}")

    ctx.mark_completed()
    print("\n" + "=" * 60)
    print(f"  Fertig: {ctx.run_dir}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# cmd_triangulate
# ---------------------------------------------------------------------------

def cmd_triangulate(args):
    """Aktualisiert/rebuildet die persistente Triangulations-DB."""
    from src.triangulator import (
        update_from_run, rebuild_from_all_runs, list_run_dirs,
    )

    if args.rebuild:
        print("Rebuild: alle Runs importieren...")
        stats = rebuild_from_all_runs()
        print(f"Rebuild fertig: {stats}")
        return

    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        runs = list_run_dirs()
        if not runs:
            print("Keine Runs mit pipeline.db unter OUTPUT_ROOT gefunden.")
            return
        run_dir = sorted(runs, key=lambda p: p.stat().st_mtime)[-1]

    print(f"Update aus: {run_dir}")
    stats = update_from_run(run_dir, mode="manual")
    print(f"Fertig: {stats}")


# ---------------------------------------------------------------------------
# cmd_curate — Phase 4: Draft-Codebook bootstrappen
# ---------------------------------------------------------------------------


def _pick_sample_interviews(company, sample_size: int) -> list[Path]:
    """Gibt bis zu ``sample_size`` Interview-Pfade zurueck (stabile Reihenfolge)."""
    return list(company.interviews[:sample_size])


def _pick_sample_documents(company, sample_size: int) -> list[Path]:
    """Sammelt bis zu ``sample_size`` PDFs aus Projekt-Ordnern (erst PDF, dann Office)."""
    picked: list[Path] = []
    for project in company.projects:
        for p in sorted(project.path.rglob("*.pdf")):
            if p.name.startswith("~$") or p.name.startswith("."):
                continue
            picked.append(p)
            if len(picked) >= sample_size:
                return picked
    # Sonstiges als Fallback
    if len(picked) < sample_size and company.sonstiges_files:
        for p in company.sonstiges_files:
            if p.suffix.lower() == ".pdf":
                picked.append(p)
                if len(picked) >= sample_size:
                    break
    return picked


def _copy_sample_to_dir(files: list[Path], target_dir: Path) -> list[Path]:
    """Kopiert Sample-Dateien flach in ein Zielverzeichnis."""
    import shutil

    target_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for src in files:
        dst = target_dir / src.name
        try:
            shutil.copy2(src, dst)
            out.append(dst)
        except OSError as e:
            print(f"  WARN: Kann {src.name} nicht kopieren: {e}")
    return out


def cmd_curate(args):
    """Bootstrap-Curation: codiert ein Sample und schreibt draft_codebook.yml.

    Flow:
      1. Company-Scan -> Sample picken (Interviews ODER Projekt-PDFs).
      2. Sample in Run-Verzeichnis kopieren (fuer Reproduzierbarkeit).
      3. Pipeline laufen lassen (``run_analysis`` bzw. PDF-Flow).
      4. ``bootstrap_codebook`` zieht Codes + Seed zusammen und schreibt YAML.
      5. CLI gibt Stats + naechste Schritte aus.
    """
    from src.company_scanner import scan_company, list_companies
    from src.codebook_curation import bootstrap_codebook
    from src.step1_analyze import run_analysis

    # 1. Company auswaehlen
    if args.company:
        company_name = args.company
    else:
        from src.cli import pick_companies
        picks = pick_companies()
        if not picks:
            print("Keine Company ausgewaehlt — Abbruch.")
            sys.exit(1)
        company_name = picks[0]

    try:
        company = scan_company(company_name)
    except FileNotFoundError as e:
        print(f"FEHLER: {e}")
        available = list_companies()
        if available:
            print(f"Verfuegbare Companies: {', '.join(available)}")
        sys.exit(1)

    source = args.from_source or "interviews"
    sample_size = args.sample_size or 4

    # 2. Recipe waehlen
    if source == "interviews":
        recipe_id = args.recipe or DEFAULT_INTERVIEW_RECIPE
    else:
        recipe_id = args.recipe or DEFAULT_DOCUMENTS_RECIPE

    # 3. Run anlegen
    ctx = create_run()
    ctx.init_state(
        mode="curate",
        recipe_id=recipe_id,
        codebase_name=args.codebase,
        transcripts=[],  # wird nach Sample-Pick gesetzt
        companies=[company_name],
        from_source=source,
        sample_size=sample_size,
    )

    print("=" * 60)
    print("  Simple BIM — Codebook-Curation")
    print(f"  Run: {ctx.run_dir.name}")
    print(f"  Company: {company.name}")
    print(f"  Quelle: {source}  |  Sample-Groesse: {sample_size}")
    print(f"  Recipe: {recipe_id}")
    if args.codebase:
        print(f"  Seed-Codebase: {args.codebase}")
    print("=" * 60)

    # 4. Sample picken
    if source == "interviews":
        sample_src = _pick_sample_interviews(company, sample_size)
    elif source == "documents":
        sample_src = _pick_sample_documents(company, sample_size)
    else:
        print(f"FEHLER: Unbekannte Quelle '{source}' (erlaubt: interviews, documents)")
        sys.exit(2)

    if not sample_src:
        print(
            f"FEHLER: Kein Sample fuer {company.name} gefunden "
            f"(Quelle={source}). Abbruch."
        )
        sys.exit(1)

    sample_dir = ctx.run_dir / "_sample_input"
    sample_files = _copy_sample_to_dir(sample_src, sample_dir)
    print(f"  Sample vorbereitet: {len(sample_files)} Datei(en) in {sample_dir}")

    # 5. Pipeline fahren
    recipe = load_recipe(recipe_id)
    recipe = _apply_coding_strategy_override(recipe, args.coding_strategy)
    codebase_text = ""
    if args.codebase:
        try:
            codebase_text = load_codebase(args.codebase)
            print(f"  Codebasis geladen: {len(codebase_text)} Zeichen")
        except FileNotFoundError as e:
            print(f"  WARN: {e}")

    analysis_result = None
    if source == "interviews":
        print("\n>>> Sample-Analyse (Interview-Flow)")
        try:
            analysis_result = run_analysis(
                recipe, ctx, transcripts_dir=sample_dir, codebase=codebase_text,
            )
        except Exception as e:
            print(f"  FEHLER bei run_analysis: {e}")
            sys.exit(1)
    else:
        print("\n>>> Sample-Analyse (Dokumenten-Flow)")
        try:
            _run_curate_documents(ctx, company, sample_files, recipe)
        except Exception as e:
            print(f"  FEHLER bei Dokument-Analyse: {e}")
            sys.exit(1)

    # 6. Draft-Codebook bauen
    print("\n>>> Bootstrap Codebook")
    draft_path, stats = bootstrap_codebook(
        ctx=ctx,
        recipe=recipe,
        sample_files=sample_files,
        codebase_seed=args.codebase,
        analysis_result=analysis_result,
    )

    print()
    print(f"  Draft-Codebook: {draft_path}")
    print(f"  - {stats.total_codes} Codes insgesamt")
    if stats.provided_codes:
        print(
            f"  - {stats.provided_codes} Codes aus Seed "
            f"({stats.unused_provided} unbenutzt)"
        )
    if stats.inductive_codes:
        print(f"  - {stats.inductive_codes} neue Codes induktiv vorgeschlagen")
    if stats.single_use:
        print(
            f"  - {stats.single_use} Codes nur 1x vorkommend "
            f"(review empfohlen!)"
        )

    # 7. Naechste-Schritte-Hinweis
    print()
    print("Naechster Schritt:")
    print("  1) Editiere die Datei manuell")
    print(
        f"  2) cp {draft_path} input/codebases/{company.name.lower()}_curated.yml"
    )
    print(
        f"  3) python main.py company {company.name} "
        f"--codebase {company.name.lower()}_curated "
        f"--coding-strategy strict"
    )

    ctx.mark_completed()


def _run_curate_documents(ctx, company, sample_files: list[Path], recipe) -> None:
    """Mini-Pipeline: nur Extraktion + Coding fuer ein PDF-Sample."""
    from src import pdf_coder as _pdf_coder_module

    # 1. In der DB registrieren
    pdf_ids: dict[str, int] = {}
    pdfs: list[dict] = []
    for src in sample_files:
        project_name = "_curate_sample"
        relative_path = f"{project_name}/{src.name}"
        pid = ctx.db.upsert_pdf(
            project=project_name,
            filename=src.name,
            relative_path=relative_path,
            path=str(src),
            file_size_kb=(src.stat().st_size // 1024 if src.exists() else 0),
        )
        pdf_ids[relative_path] = pid
        pdfs.append({
            "project": project_name,
            "filename": src.name,
            "relative_path": relative_path,
            "path": str(src),
            "size_kb": src.stat().st_size // 1024,
        })

    if not pdfs:
        print("  Keine PDFs im Sample — Abbruch der Dokument-Curation.")
        return

    # 2. Extraction
    extractions = _pdf_coder_module.run_extraction(pdfs, ctx, pdf_ids)
    if not extractions:
        print("  Keine Extraktionen — Abbruch.")
        return

    # 3. Coding
    _pdf_coder_module.run_coding(
        pdfs, extractions, recipe, codesystem="",
        ctx=ctx, pdf_ids=pdf_ids,
    )


# ---------------------------------------------------------------------------
# cmd_resume
# ---------------------------------------------------------------------------

def cmd_resume(args):
    """Setzt den letzten unterbrochenen Run fort (transcripts-Flow)."""
    interrupted = find_interrupted_runs()
    if not interrupted:
        print("Kein unterbrochener Run gefunden.")
        sys.exit(1)
    ctx = resume_run(interrupted[0].run_dir)
    state = ctx.get_state()
    recipe_id = state.get("recipe_id", DEFAULT_INTERVIEW_RECIPE)
    codebase_name = state.get("codebase_name")
    print(f"Setze Run fort: {ctx.run_dir.name}")
    run_transcripts_pipeline(ctx, recipe_id, codebase_name)


# ---------------------------------------------------------------------------
# cmd_testrun — vordefinierte Testruns aus src/testruns.py
# ---------------------------------------------------------------------------

def cmd_testrun(args):
    """Fuehrt einen vordefinierten Testrun aus."""
    from src.cli import _pick, pick_recipe, pick_recipe_pair, pick_codebook

    with spinner("Pipeline-Module laden...", phase="scan"):
        from src import pdf_coder as _pdf_coder_module
        from src.pdf_scanner import build_manifest, save_manifest, print_manifest_summary
        from src.pdf_classifier import split_by_type

    # ---- 1. Profil waehlen ----
    if args.profile:
        profile_id = args.profile
    else:
        profiles = list_profiles()
        options = [f"{p.id} -- {p.name}: {p.description[:60]}..." for p in profiles]
        choice = _pick("Welches Testrun-Profil?", options)
        if choice is None:
            return
        profile_id = choice.split(" -- ")[0]

    try:
        profile = get_profile(profile_id)
    except KeyError:
        available = ", ".join(p.id for p in list_profiles())
        print_error(f"Profil '{profile_id}' nicht gefunden. Verfuegbar: {available}")
        sys.exit(1)

    print_header(f"Testrun: {profile.name}", profile.description)

    # ---- 2. Methode (Recipe) waehlen ----
    recipe_id = getattr(args, "recipe", None)
    recipe_interviews_id = None
    if not recipe_id:
        has_interviews = bool(profile.selected_interviews)
        has_documents = bool(profile.selected_pdfs)
        if has_interviews and has_documents:
            recipe_interviews_id, recipe_id = pick_recipe_pair(
                default_interviews=profile.recipe_interviews or "mayring",
                default_documents=profile.recipe_id,
            )
        elif has_interviews:
            recipe_id = pick_recipe(
                category="interviewanalysis",
                default_id=profile.recipe_interviews or "mayring",
            )
        else:
            recipe_id = pick_recipe(
                category="documentanalysis",
                default_id=profile.recipe_id,
            )

    # ---- 3. Codebook + Coding-Strategy waehlen ----
    codebase_name = getattr(args, "codebase", None)
    coding_strategy = None
    codesystem = ""
    codebase_codes: dict | None = None
    if not codebase_name:
        codebase_name, coding_strategy = pick_codebook()
    if codebase_name:
        codesystem = load_codebase(codebase_name)
        print_success(f"Codebook: {codebase_name} ({len(codesystem)} Zeichen)")
        try:
            codebase_codes = parse_codebase_yaml(codebase_name) or None
        except Exception as e:
            print_warning(f"Codebasis konnte nicht geparst werden: {e}")
            codebase_codes = None

    # ---- 4. PDFs bauen ----
    print_step("Eingabedaten laden", phase="input")
    try:
        pdfs = build_testrun_pdfs(profile)
    except FileNotFoundError as e:
        print_error(str(e))
        sys.exit(1)

    # ---- 5. Run anlegen ----
    if args.resume:
        interrupted = find_interrupted_runs()
        if not interrupted:
            print_error("Kein unterbrochener Run gefunden.")
            sys.exit(1)
        ctx = resume_run(interrupted[0].run_dir)
        print_success(f"Setze Run fort: {ctx.run_dir.name}")
    else:
        ctx = create_run()
        ctx.init_state(
            recipe_id=recipe_id,
            codebase_name=codebase_name,
            transcripts=profile.selected_interviews,
            mode=f"testrun_{profile.id}",
        )

    manifest = build_manifest(pdfs)
    save_manifest(manifest, ctx.cache_dir / "manifest.json")
    print_manifest_summary(manifest)

    pdf_ids = _pdf_coder_module._register_pdfs(pdfs, ctx)

    print_summary([
        ("Run", ctx.run_dir.name),
        ("DB", ctx.db.db_path.name),
        ("PDFs", str(len(pdfs))),
        ("Klassifikation", profile.classify_mode),
        ("Methode (Dokumente)", recipe_id),
        ("Methode (Interviews)", recipe_interviews_id or "--"),
        ("Codebook", codebase_name or "(induktiv)"),
        ("Coding-Strategy", coding_strategy or "recipe-default"),
        ("Token-Budget", profile.token_budget_info),
    ])

    # ---- 6. Klassifikation ----
    print_step("Klassifikation", profile.classify_mode, phase="scan")
    classifications = _pdf_coder_module.run_classification(
        pdfs, ctx, pdf_ids, classify_mode=profile.classify_mode,
    )

    # ---- 7. Aufteilen nach Typ ----
    groups = split_by_type(pdfs, classifications)
    text_pdfs = groups.get("text", []) + groups.get("mixed", [])
    visual_pdfs = groups.get("plan", []) + groups.get("photo", [])
    print_success(f"Aufgeteilt: {len(text_pdfs)} Text/Mixed, {len(visual_pdfs)} Plan/Foto")

    pdf_results = []
    visual_qdpx_results = []
    recipe = load_recipe(recipe_id)
    recipe = _apply_coding_strategy_override(recipe, coding_strategy)

    # ---- 8. Text-Pipeline ----
    if text_pdfs:
        print_step("Extraktion + Code-Zuweisung", f"{len(text_pdfs)} PDFs", phase="ai")
        extractions = _pdf_coder_module.run_extraction(text_pdfs, ctx, pdf_ids)
        pdf_results = _pdf_coder_module.run_coding(
            text_pdfs, extractions, recipe, codesystem=codesystem,
            ctx=ctx, pdf_ids=pdf_ids,
        )
        results_path = ctx.run_dir / "pdf_analysis_results.json"
        _pdf_coder_module.save_results(pdf_results, results_path)

    # ---- 9. Vision-Pipeline ----
    if visual_pdfs and not profile.skip_visual_detail:
        print_step("Vision-Pipeline", f"{len(visual_pdfs)} PDFs", phase="ai")
        visual_qdpx_results = _pdf_coder_module.run_visual(
            visual_pdfs, ctx, pdf_ids,
            skip_detail=False,
            max_visual_tokens=profile.max_visual_tokens,
        )

    # ---- 10. Annotation (nur fuer PDFs -- PDFs gehen NICHT in QDPX,
    #          sondern werden manuell in MAXQDA importiert, siehe CLAUDE.md) ----
    print_step("Annotation", "1 Farbe, Code im Comment", phase="annotate")
    _pdf_coder_module.run_annotation(ctx, recipe=recipe)

    # ---- 11. Interview-Flow (nur wenn Profil Interviews hat) ----
    #          QDPX-Export ist ausschliesslich fuer Interviews.
    qdpx_target = None
    if profile.selected_interviews:
        from src.step1_analyze import run_analysis
        from src.step3_qdpx import generate_qdpx
        from src.config import COMPANIES_DIR

        print_step(
            "Interview-Analyse",
            f"{len(profile.selected_interviews)} Interview(s)",
            phase="ai",
        )

        iv_recipe_id = recipe_interviews_id or profile.recipe_interviews or "mayring"
        iv_recipe = load_recipe(iv_recipe_id)
        iv_recipe = _apply_coding_strategy_override(iv_recipe, coding_strategy)

        if profile.company_name:
            iv_sample_dir = ctx.company_interview_sample_dir(profile.company_name)
        else:
            iv_sample_dir = ctx.run_dir / "_interview_sample"
        company_iv_dir = COMPANIES_DIR / (profile.company_name or "") / "Interviews"
        iv_sources = [company_iv_dir / n for n in profile.selected_interviews]
        missing_iv = [p.name for p in iv_sources if not p.exists()]
        if missing_iv:
            print_warning(f"Interviews nicht gefunden: {', '.join(missing_iv)}")
        _copy_sample_to_dir([p for p in iv_sources if p.exists()], iv_sample_dir)

        # Company-scoped Output-Pfade fuer Interview-Analyse
        analysis_json_override = None
        prompts_dir_override = None
        responses_dir_override = None
        if profile.company_name:
            analysis_json_override = ctx.company_analysis_json(profile.company_name)
            prompts_dir_override = ctx.company_prompts_dir(profile.company_name)
            responses_dir_override = ctx.company_responses_dir(profile.company_name)

        iv_result = run_analysis(
            iv_recipe, ctx, iv_sample_dir, codesystem,
            analysis_json_override=analysis_json_override,
            prompts_dir_override=prompts_dir_override,
            responses_dir_override=responses_dir_override,
        )

        # ---- 12. QDPX-Export (nur Interviews!) ----
        print_step("QDPX-Export", "Interviews", phase="output")
        if profile.company_name:
            qdpx_target = ctx.company_qdpx_path(profile.company_name, "interviews.qdpx")
        else:
            qdpx_target = ctx.qdpx_file
        qdpx_target.parent.mkdir(parents=True, exist_ok=True)
        generate_qdpx(
            iv_result, qdpx_target,
            codebase_codes=codebase_codes,
            codebase_name=codebase_name,
        )
        print_success(f"QDPX: {qdpx_target}")

    # ---- Zusammenfassung ----
    step_summary = ctx.db.get_step_summary()
    if step_summary:
        console.print("\n[bold]Pipeline-Status:[/bold]")
        for s, counts in sorted(step_summary.items()):
            parts = [f"{v} {k}" for k, v in counts.items()]
            console.print(f"  {s}: {', '.join(parts)}")

    # Pivot-Export (wide-format Excel mit allen Codings)
    try:
        from src.pivot_export import build_pivot_excel
        build_pivot_excel(
            ctx, ctx.run_dir / "pivot_results.xlsx",
            codebase_codes=codebase_codes,
        )
    except Exception as e:
        print_warning(f"Pivot-Export fehlgeschlagen: {e}")

    ctx.mark_completed()
    print_step("Fertig!", str(ctx.run_dir), phase="output")
    if qdpx_target:
        console.print(f"  [dim]QDPX (Interviews):[/dim] {qdpx_target}")
    console.print(f"  [dim]Annotierte PDFs:[/dim]   {ctx.annotated_dir}")


# ---------------------------------------------------------------------------
# Argparse setup
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Baut den Top-Level-Parser mit allen Subcommands."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Simple BIM Pipeline — Interview- und Dokumentenanalyse",
        epilog="Ohne Subcommand startet der interaktive Modus.",
    )
    subs = parser.add_subparsers(dest="command")

    # --- transcripts -----------------------------------------------------
    p_t = subs.add_parser(
        "transcripts",
        help="Interview-Analyse (Mayring etc.)",
    )
    p_t.add_argument(
        "--recipe", type=str, default=None,
        help=f"Analyse-Methode (default: {DEFAULT_INTERVIEW_RECIPE})",
    )
    p_t.add_argument(
        "--codebase", type=str, default=None,
        help="Codebasis aus CODEBASES_DIR",
    )
    p_t.add_argument(
        "--coding-strategy", type=str,
        choices=list(CODING_STRATEGIES), default=None,
        help="Ueberschreibt Recipe.coding_strategy (strict|hybrid|inductive)",
    )
    p_t.add_argument(
        "--skip-analysis", action="store_true",
        help="Ueberspringe KI-Analyse, nutze vorhandenes JSON",
    )
    p_t.add_argument(
        "--step", type=int, choices=[1, 2, 3, 4], default=None,
        help="Nur einen bestimmten Schritt ausfuehren",
    )
    p_t.set_defaults(func=cmd_transcripts)

    # --- documents -------------------------------------------------------
    p_d = subs.add_parser(
        "documents",
        help="PDF-/Dokument-Analyse (pdf_coder)",
    )
    p_d.add_argument("--project", type=str, default=None,
                     help="Nur ein bestimmtes Projekt analysieren")
    p_d.add_argument("--recipe", type=str, default=None,
                     help=f"Analyse-Recipe (default: {DEFAULT_DOCUMENTS_RECIPE})")
    p_d.add_argument("--qdpx", type=str, default=None,
                     help="Bestehende .qdpx zum Erweitern")
    p_d.add_argument(
        "--step", type=str,
        choices=["extract", "classify", "code", "visual", "annotate", "export"],
        default=None, help="Nur einen bestimmten Schritt ausfuehren",
    )
    p_d.add_argument(
        "--mode", type=str, choices=["text", "visual", "classify"],
        default=None, help="Subset der PDFs",
    )
    p_d.add_argument(
        "--classify-mode", type=str,
        choices=["local", "llm", "hybrid"], default="local",
        help="Klassifikationsmodus",
    )
    p_d.add_argument(
        "--coding-strategy", type=str,
        choices=list(CODING_STRATEGIES), default=None,
        help="Ueberschreibt Recipe.coding_strategy",
    )
    p_d.add_argument("--skip-plans", action="store_true",
                     help="Plaene rausfiltern")
    p_d.add_argument("--skip-pattern", action="append", default=[],
                     metavar="REGEX",
                     help="Zusaetzliches Filter-Pattern (mehrfach moeglich)")
    p_d.add_argument("--no-convert-office", action="store_true",
                     help="docx/xlsx NICHT zu PDF konvertieren")
    p_d.set_defaults(func=cmd_documents)

    # --- company ---------------------------------------------------------
    p_c = subs.add_parser(
        "company",
        help="Company-Modus: Interviews + Projektdokumente trianguliert",
    )
    p_c.add_argument(
        "companies", nargs="*",
        help="Company-Namen (leer = interaktive Auswahl)",
    )
    p_c.add_argument("--all", action="store_true",
                     help="Alle Companies aus COMPANIES_DIR")
    p_c.add_argument("--recipe-interviews", type=str, default=None,
                     help=f"Recipe fuer Interviews (default: {DEFAULT_INTERVIEW_RECIPE})")
    p_c.add_argument("--recipe-documents", type=str, default=None,
                     help=f"Recipe fuer Dokumente (default: {DEFAULT_DOCUMENTS_RECIPE})")
    p_c.add_argument("--codebase", type=str, default=None,
                     help="Codebasis aus CODEBASES_DIR")
    p_c.add_argument(
        "--coding-strategy", type=str,
        choices=list(CODING_STRATEGIES), default=None,
        help="Ueberschreibt Recipe.coding_strategy",
    )
    p_c.add_argument("--project", action="append", default=[],
                     metavar="NAME",
                     help="Nur diese Projekte verarbeiten (wiederholbar, z.B. --project BOE --project PBN)")
    p_c.add_argument("--skip-plans", action="store_true",
                     help="Plaene aus PDF-Flow rausfiltern")
    p_c.add_argument("--skip-pattern", action="append", default=[],
                     metavar="REGEX", help="Zusaetzliches Filter-Pattern")
    p_c.add_argument("--no-convert-office", action="store_true",
                     help="docx/xlsx NICHT zu PDF konvertieren")
    p_c.add_argument("--no-triangulate", action="store_true",
                     help="Triangulations-DB nach Lauf nicht aktualisieren")
    p_c.set_defaults(func=cmd_company)

    # --- curate (Phase 4) ------------------------------------------------
    p_cur = subs.add_parser(
        "curate",
        help="Draft-Codebook aus einem Sample bootstrappen",
    )
    p_cur.add_argument(
        "--company", type=str, default=None,
        help="Company-Name (ansonsten interaktive Auswahl)",
    )
    p_cur.add_argument(
        "--from", dest="from_source", type=str,
        choices=["interviews", "documents"], default="interviews",
        help="Welche Quelle als Sample dienen soll (default: interviews)",
    )
    p_cur.add_argument(
        "--codebase", type=str, default=None,
        help="Seed-Codebase aus CODEBASES_DIR (optional)",
    )
    p_cur.add_argument(
        "--sample-size", type=int, default=4,
        help="Anzahl Sample-Dateien (default: 4)",
    )
    p_cur.add_argument(
        "--recipe", type=str, default=None,
        help=(
            f"Recipe (default: {DEFAULT_INTERVIEW_RECIPE} bei interviews, "
            f"{DEFAULT_DOCUMENTS_RECIPE} bei documents)"
        ),
    )
    p_cur.add_argument(
        "--coding-strategy", type=str,
        choices=list(CODING_STRATEGIES), default=None,
        help="Ueberschreibt Recipe.coding_strategy (strict|hybrid|inductive)",
    )
    p_cur.set_defaults(func=cmd_curate)

    # --- triangulate -----------------------------------------------------
    p_tri = subs.add_parser(
        "triangulate",
        help="Triangulations-DB aus Runs aufbauen/aktualisieren",
    )
    p_tri.add_argument("--company", default=None,
                       help="Nur Daten dieser Company")
    p_tri.add_argument("--rebuild", action="store_true",
                       help="Drop & re-import alle Runs")
    p_tri.add_argument("--run-dir", default=None,
                       help="Spezifischer Run, default=letzter")
    p_tri.set_defaults(func=cmd_triangulate)

    # --- testrun ---------------------------------------------------------
    p_test = subs.add_parser(
        "testrun",
        help="Vordefinierte Testruns (boe, company, plans)",
    )
    p_test.add_argument(
        "profile", nargs="?", default=None,
        choices=["boe", "company", "plans"],
        help="Testrun-Profil (leer = interaktive Auswahl)",
    )
    p_test.add_argument(
        "--recipe", type=str, default=None,
        help="Analyse-Methode ueberschreiben (sonst interaktiv)",
    )
    p_test.add_argument(
        "--codebase", type=str, default=None,
        help="Codebook aus CODEBASES_DIR",
    )
    p_test.add_argument(
        "--resume", action="store_true",
        help="Letzten unterbrochenen Run fortsetzen",
    )
    p_test.set_defaults(func=cmd_testrun)

    # --- resume ----------------------------------------------------------
    p_r = subs.add_parser("resume", help="Letzten unterbrochenen Run fortsetzen")
    p_r.set_defaults(func=cmd_resume)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        run_interactive()
        return

    args.func(args)


if __name__ == "__main__":
    main()
