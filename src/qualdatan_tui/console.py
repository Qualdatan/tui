"""Interaktives CLI fuer die Analyse-Pipeline mit Rich-UI."""

import sys
from pathlib import Path

from contextlib import contextmanager

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box

from qualdatan_core.config import TRANSCRIPTS_DIR, CODEBASES_DIR, DEFAULT_RECIPE
from qualdatan_core.recipe import list_recipes, list_codebases
from qualdatan_core.run_context import find_interrupted_runs

# Shared console instance – importable by other modules
console = Console()

# ---------------------------------------------------------------------------
#  Helper functions for styled output
# ---------------------------------------------------------------------------

def print_header(title: str, subtitle: str = "") -> None:
    """Prints a styled banner panel with title and optional subtitle."""
    content = f"[bold cyan]{title}[/bold cyan]"
    if subtitle:
        content += f"\n[dim]{subtitle}[/dim]"
    console.print()
    console.print(
        Panel(
            content,
            box=box.ROUNDED,
            border_style="cyan",
            padding=(1, 2),
        )
    )


PHASE_STYLES = {
    "input":    ("\U0001f4e5", "blue"),          # Eingabe
    "scan":     ("\U0001f50d", "sky_blue1"),      # Scan/Klassifikation
    "ai":       ("\U0001f916", "purple"),         # KI-Verarbeitung
    "annotate": ("\u270f\ufe0f", "dark_orange"),  # Annotation
    "output":   ("\U0001f4e6", "green"),          # Output
    "tri":      ("\U0001f517", "medium_purple"),  # Triangulation
}


def print_step(step: str, detail: str = "", phase: str = "ai") -> None:
    """Prints a pipeline step indicator with optional phase styling."""
    if phase in PHASE_STYLES:
        emoji, color = PHASE_STYLES[phase]
        msg = f"[bold {color}]{emoji} {step}[/bold {color}]"
    else:
        msg = f"[bold blue]>> {step}[/bold blue]"
    if detail:
        msg += f"  [dim]{detail}[/dim]"
    console.print(msg)


def print_success(msg: str) -> None:
    """Prints a green success message."""
    console.print(f"[bold green]  [OK][/bold green] {msg}")


def print_warning(msg: str) -> None:
    """Prints a yellow warning message."""
    console.print(f"[bold yellow]  [!][/bold yellow] {msg}")


def print_error(msg: str) -> None:
    """Prints a red error message."""
    console.print(f"[bold red]  [FEHLER][/bold red] {msg}")


@contextmanager
def spinner(message: str, phase: str = "ai"):
    """Context manager that shows a styled spinner while work is done."""
    if phase in PHASE_STYLES:
        emoji, color = PHASE_STYLES[phase]
        styled = f"[{color}]{emoji} {message}[/{color}]"
    else:
        styled = message
    with console.status(styled, spinner="dots"):
        yield


def print_summary(rows: list[tuple[str, str]]) -> None:
    """Prints a key/value summary table."""
    table = Table(box=box.ROUNDED, border_style="dim", show_header=False, padding=(0, 1))
    table.add_column("Eigenschaft", style="bold cyan", no_wrap=True)
    table.add_column("Wert", style="white")
    for key, value in rows:
        table.add_row(key, value)
    console.print(table)


# ---------------------------------------------------------------------------
#  Core selection helpers
# ---------------------------------------------------------------------------

def _pick(prompt: str, options: list[str], allow_skip: bool = False) -> str | None:
    """Zeigt eine nummerierte Auswahl und gibt die Wahl zurueck."""
    console.print()
    console.print(f"[bold]{prompt}[/bold]")

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("Nr", style="bold cyan", justify="right", width=4)
    table.add_column("Option", style="white")

    for i, opt in enumerate(options, 1):
        table.add_row(str(i), opt)
    if allow_skip:
        table.add_row("0", "[dim]Ueberspringen[/dim]")
    console.print(table)

    while True:
        try:
            choice = Prompt.ask("[cyan]Auswahl[/cyan]").strip()
            if allow_skip and choice == "0":
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                print_success(options[idx])
                return options[idx]
        except (ValueError, EOFError):
            pass
        print_warning("Ungueltige Auswahl, bitte erneut versuchen.")


def _pick_multiple(prompt: str, options: list[str]) -> list[str]:
    """Zeigt eine nummerierte Auswahl, erlaubt Mehrfachauswahl oder 'alle'."""
    console.print()
    console.print(f"[bold]{prompt}[/bold]")

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("Nr", style="bold cyan", justify="right", width=4)
    table.add_column("Option", style="white")

    for i, opt in enumerate(options, 1):
        table.add_row(str(i), opt)
    table.add_row("a", "[dim]Alle auswaehlen[/dim]")
    console.print(table)

    while True:
        try:
            choice = Prompt.ask(
                "[cyan]Auswahl[/cyan] [dim](Nummern kommagetrennt, oder 'a' fuer alle)[/dim]"
            ).strip()
            if choice.lower() == "a":
                print_success(f"Alle {len(options)} ausgewaehlt")
                return options
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
            selected = [options[i] for i in indices if 0 <= i < len(options)]
            if selected:
                print_success(f"{len(selected)} ausgewaehlt")
                return selected
        except (ValueError, EOFError, IndexError):
            pass
        print_warning("Ungueltige Auswahl, bitte erneut versuchen.")


def _confirm(prompt: str) -> bool:
    """Ja/Nein-Frage."""
    console.print()
    while True:
        choice = Prompt.ask(f"[bold]{prompt}[/bold] [dim]\\[j/n][/dim]").strip().lower()
        if choice in ("j", "ja", "y", "yes"):
            return True
        if choice in ("n", "nein", "no"):
            return False


# ---------------------------------------------------------------------------
#  High-level dialogs
# ---------------------------------------------------------------------------

def pick_recipe(category: str | None = None, default_id: str | None = None) -> str:
    """Filtered recipe selection.

    Args:
        category: One of 'interviewanalysis', 'documentanalysis', 'combined',
                  or None to show all recipes.
        default_id: Recipe ID to highlight as default.

    Returns:
        The selected recipe ID.
    """
    recipes = list_recipes()
    if category is not None:
        recipes = [r for r in recipes if r["category"] in (category, "combined")]

    if not recipes:
        print_error("Keine passenden Methoden gefunden.")
        sys.exit(1)

    if len(recipes) == 1:
        chosen = recipes[0]
        print_success(f"Methode automatisch gewaehlt: {chosen['id']} -- {chosen['name']}")
        return chosen["id"]

    console.print()
    label = category or "alle"
    console.print(f"[bold]Welche Analyse-Methode? [dim]({label})[/dim][/bold]")

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("Nr", style="bold cyan", justify="right", width=4)
    table.add_column("Option", style="white")

    for i, r in enumerate(recipes, 1):
        line = f"{r['id']} -- {r['name']}"
        if r["description"]:
            line += f"  [dim]{r['description']}[/dim]"
        if default_id and r["id"] == default_id:
            line += "  [dim](Standard)[/dim]"
        table.add_row(str(i), line)
    console.print(table)

    while True:
        prompt_hint = ""
        if default_id:
            prompt_hint = f" [dim](Enter = {default_id})[/dim]"
        choice = Prompt.ask(f"[cyan]Auswahl[/cyan]{prompt_hint}").strip()

        # Allow pressing Enter for default
        if not choice and default_id:
            for r in recipes:
                if r["id"] == default_id:
                    print_success(f"Methode: {r['id']}")
                    return r["id"]

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(recipes):
                chosen = recipes[idx]
                print_success(f"Methode: {chosen['id']}")
                return chosen["id"]
        except (ValueError, EOFError):
            pass
        print_warning("Ungueltige Auswahl, bitte erneut versuchen.")


def pick_recipe_pair(
    default_interviews: str = "mayring",
    default_documents: str = "pdf_analyse",
) -> tuple[str, str]:
    """Pick recipes for runs that process both interviews and documents.

    Returns:
        Tuple of (interview_recipe_id, document_recipe_id).
    """
    choice = _pick(
        "Gleiche Methode fuer Interviews und Dokumente?",
        [
            "Gleiche Methode (nur 'combined'-Methoden)",
            "Getrennte Methoden fuer Interviews und Dokumente",
        ],
    )

    if "Gleiche" in choice:
        recipe_id = pick_recipe(category="combined")
        return (recipe_id, recipe_id)

    interview_id = pick_recipe(
        category="interviewanalysis", default_id=default_interviews,
    )
    document_id = pick_recipe(
        category="documentanalysis", default_id=default_documents,
    )
    return (interview_id, document_id)


def pick_codebook() -> tuple[str | None, str]:
    """Interactive codebook and coding strategy selection.

    Returns:
        Tuple of (codebase_name_or_None, coding_strategy).
    """
    options = [
        "\U0001f513 Ohne Codebook (induktiv) -- Codes werden frei aus dem Material abgeleitet",
        "\U0001f4d6 Mit Codebook + induktiv -- Codebook als Basis, neue Codes erlaubt",
        "\U0001f512 Nur Codebook (strict) -- Ausschliesslich vordefinierte Codes",
    ]
    choice = _pick("Coding-Strategie waehlen:", options)

    if "Ohne Codebook" in choice:
        return (None, "inductive")

    # Option 2 or 3: need a codebook
    codebases = list_codebases()
    if not codebases:
        print_warning("Keine Codebasen in input/codebases/ gefunden.")
        console.print("  [dim]Fallback: induktive Codierung[/dim]")
        return (None, "inductive")

    codebase_name = _pick("Welche Codebasis?", codebases)
    print_success(f"Codebasis: {codebase_name}")

    if "Mit Codebook" in choice:
        return (codebase_name, "hybrid")
    return (codebase_name, "strict")


def pick_companies() -> list[str]:
    """Interaktive Mehrfachauswahl von Companies aus COMPANIES_DIR.

    Leere Liste wenn keine Companies gefunden werden — der Aufrufer
    entscheidet, wie darauf zu reagieren ist.
    """
    from .company_scanner import list_companies
    from .config import COMPANIES_DIR

    available = list_companies()
    if not available:
        print_warning(f"Keine Companies in {COMPANIES_DIR} gefunden.")
        return []
    return _pick_multiple(
        "Welche Companies sollen analysiert werden?",
        available,
    )


def check_interrupted_runs() -> dict | None:
    """Prueft auf unterbrochene Runs und bietet Wiederaufnahme an."""
    interrupted = find_interrupted_runs()
    if not interrupted:
        return None

    console.print()
    console.print(
        Panel(
            "[bold yellow]Unterbrochene Runs gefunden![/bold yellow]",
            box=box.ROUNDED,
            border_style="yellow",
            padding=(0, 2),
        )
    )

    for i, ctx in enumerate(interrupted):
        state = ctx.get_state()
        done = len(state.get("completed_transcripts", []))
        total = len(state.get("transcripts", []))
        steps = state.get("steps_completed", [])
        recipe = state.get("recipe_id", "?")
        started = state.get("started_at", "?")[:19]

        run_table = Table(
            title=f"[bold cyan]\\[{i+1}] {ctx.run_dir.name}[/bold cyan]",
            box=box.ROUNDED,
            border_style="dim",
            show_header=False,
            padding=(0, 1),
        )
        run_table.add_column("Key", style="bold", no_wrap=True)
        run_table.add_column("Value")
        run_table.add_row("Recipe", recipe)
        run_table.add_row("Transkripte", f"{done}/{total}")
        run_table.add_row("Schritte", str(steps))
        run_table.add_row("Gestartet", started)

        pending = ctx.get_pending_transcripts()
        if pending:
            run_table.add_row("Ausstehend", ", ".join(pending))

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
            run_table.add_row("Fehlende Schritte", ", ".join(missing_steps))

        console.print(run_table)

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


