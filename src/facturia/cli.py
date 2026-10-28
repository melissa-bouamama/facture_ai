"""Interface en ligne de commande : `facturia --help`."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .normalize import fmt_amount

app = typer.Typer(
    add_completion=False,
    help="factur-ia : du PDF à la facture électronique conforme (Factur-X / EN 16931).",
)
console = Console()

BACKEND_HELP = (
    "Extracteur : rules (déterministe), llm (LLM local/API), hybrid (règles + LLM si doute)."
)
DECISION_STYLE = {"ready": "bold green", "fix_required": "bold yellow", "human_review": "bold red"}
DECISION_LABEL = {
    "ready": "PRÊTE À ÉMETTRE",
    "fix_required": "À CORRIGER",
    "human_review": "REVUE HUMAINE",
}


def _print_report(report) -> None:
    inv = report.invoice
    style = DECISION_STYLE[report.decision.value]
    console.print(
        Panel.fit(
            f"[{style}]{DECISION_LABEL[report.decision.value]}[/]  ·  source : {report.source}  ·  "
            f"extracteur : {report.backend}  ·  confiance : {report.mean_confidence:.2f}\n"
            + "\n".join(f"• {r}" for r in report.decision_reasons),
            title=f"Facture {inv.number or '?'}",
        )
    )
    t = Table(show_header=False, box=None)
    t.add_row(
        "Vendeur",
        f"{inv.seller.name or '—'}  (SIREN {inv.seller.siren or '—'}, TVA {inv.seller.vat_id or '—'})",
    )
    t.add_row("Client", f"{inv.buyer.name or '—'}  (SIREN {inv.buyer.siren or '—'})")
    t.add_row("Dates", f"émise le {inv.issue_date or '—'}, échéance {inv.due_date or '—'}")
    t.add_row(
        "Montants",
        f"HT {fmt_amount(inv.total_without_vat)} · TVA {fmt_amount(inv.total_vat)} · TTC {fmt_amount(inv.total_with_vat)} {inv.currency}",
    )
    t.add_row("Lignes", str(len(inv.lines)))
    t.add_row("Catégorie", inv.operation_category.label if inv.operation_category else "—")
    console.print(t)
    if report.issues:
        it = Table(title="Anomalies", show_lines=False)
        for col in ("Gravité", "Code", "Champ", "Règle", "Message"):
            it.add_column(col)
        for i in report.issues:
            sev = {
                "error": "[red]erreur[/]",
                "warning": "[yellow]alerte[/]",
                "info": "[blue]info[/]",
            }[i.severity.value]
            msg = i.message + (f"\n[dim]→ suggestion : {i.suggestion}[/]" if i.suggestion else "")
            it.add_row(sev, i.code, i.bt or "", i.rule or "", msg)
        console.print(it)
    if report.fine_exposure_eur:
        console.print(
            f"Exposition estimée aux amendes (15 € par mention, plafond 25 %) : [bold]{fmt_amount(report.fine_exposure_eur)} €[/]"
        )
    if report.xml_valid is not None:
        console.print(
            f"XML Factur-X valide : {'[green]oui[/]' if report.xml_valid else '[red]non[/]'}"
        )
        for f in report.xml_failures:
            if f["flag"] in ("fatal", "error"):
                console.print(f"  [red]✗[/] {f['schematron']} {f['id']} : {f['message'][:160]}")
    for n in report.notes:
        console.print(f"[dim]note : {n}[/]")
    console.print(f"[dim]temps : {report.timings_ms}[/]")


@app.command()
def analyze(
    pdf: Path = typer.Argument(..., exists=True, help="Facture PDF (native ou scannée)."),
    backend: str = typer.Option("rules", "--backend", "-b", help=BACKEND_HELP),
    as_json: bool = typer.Option(False, "--json", help="Affiche le rapport JSON brut."),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Écrit le rapport JSON dans ce fichier."
    ),
    force_ocr: bool = typer.Option(
        False, "--ocr", help="Force l'OCR même si le PDF contient du texte."
    ),
):
    """Extrait les données d'une facture et contrôle sa conformité."""
    from .pipeline import process

    report = process(pdf, extractor=backend, force_ocr=force_ocr).report
    payload = report.model_dump_json(indent=2)
    if out:
        out.write_text(payload, encoding="utf-8")
    if as_json:
        console.print_json(payload)
    else:
        _print_report(report)


@app.command()
def convert(
    pdf: Path = typer.Argument(..., exists=True, help="Facture PDF à convertir."),
    output: Path | None = typer.Option(None, "--output", "-o", help="PDF Factur-X de sortie."),
    backend: str = typer.Option("rules", "--backend", "-b", help=BACKEND_HELP),
    schematron: bool = typer.Option(
        True,
        "--schematron/--no-schematron",
        help="Valide aussi contre les schematrons EN 16931 et BR-FR.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Produit le Factur-X même si la facture doit être revue ou corrigée."
    ),
):
    """Convertit une facture PDF en Factur-X (PDF + XML CII EN 16931 embarqué)."""
    from .pipeline import Decision, process

    result = process(pdf, extractor=backend, facturx=True, schematron=schematron)
    report = result.report
    _print_report(report)
    if report.decision != Decision.READY and not force:
        console.print(
            "[yellow]Conversion non écrite : la facture n'est pas prête (utilisez --force pour l'écrire quand même).[/]"
        )
        raise typer.Exit(code=2)
    if result.facturx_pdf is None:
        console.print(
            "[red]Impossible de produire le Factur-X (données insuffisantes ou XML invalide).[/]"
        )
        raise typer.Exit(code=1)
    output = output or pdf.with_name(pdf.stem + "_facturx.pdf")
    output.write_bytes(result.facturx_pdf)
    output.with_suffix(".xml").write_bytes(result.xml)
    console.print(f"[green]✓[/] {output}  (+ {output.with_suffix('.xml').name})")


@app.command()
def generate(
    folder: Path = typer.Argument(..., help="Dossier de sortie."),
    n: int = typer.Option(50, "--n", help="Nombre de factures."),
    seed: int = typer.Option(42, "--seed"),
    scan_ratio: float = typer.Option(
        0.3, "--scan-ratio", help="Part de factures dégradées en scan."
    ),
    heldout: bool = typer.Option(False, "--heldout", help="Utilise le gabarit hors distribution."),
):
    """Génère un jeu de factures synthétiques annotées (PDF + JSON)."""
    from .synth import HELDOUT_TEMPLATES, generate_dataset

    paths = generate_dataset(
        folder,
        n=n,
        seed=seed,
        scanned_ratio=scan_ratio,
        templates=HELDOUT_TEMPLATES if heldout else None,
    )
    console.print(f"[green]✓[/] {len(paths)} factures écrites dans {folder}")


@app.command()
def evaluate(
    folder: Path = typer.Argument(..., exists=True, help="Dossier de PDF + JSON annotés."),
    backend: str = typer.Option("rules", "--backend", "-b", help=BACKEND_HELP),
    out: Path | None = typer.Option(None, "--out", "-o", help="Écrit les résultats en Markdown."),
    title: str = typer.Option("Résultats", "--title"),
    limit: int | None = typer.Option(None, "--limit"),
):
    """Mesure l'extraction et la détection d'anomalies sur un jeu annoté."""
    from .evaluate import evaluate as run

    result = run(folder, extractor=backend, limit=limit)
    md = result.to_markdown(title)
    console.print(md)
    if out:
        out.write_text(md, encoding="utf-8")
        out.with_suffix(".errors.json").write_text(
            json.dumps(result.errors, ensure_ascii=False, indent=2), encoding="utf-8"
        )


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000):
    """Lance l'API HTTP (documentation interactive sur /docs)."""
    import uvicorn

    uvicorn.run("facturia.api:app", host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    app()
