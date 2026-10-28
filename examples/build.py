"""Régénère les exemples du dépôt : PDF d'entrée, rapports JSON et Factur-X de sortie.

python examples/build_examples.py
"""

from __future__ import annotations

import random
from pathlib import Path

from rich.console import Console

from facturia.cli import _print_report
from facturia.pipeline import process
from facturia.synth import random_invoice, render_pdf, simulate_scan

HERE = Path(__file__).parent
DOCS_IMG = HERE.parent / "docs" / "img"


def _invoice(template: str, wanted_issues: set[str], seed: int = 0):
    """Première facture générée (graine ≥ seed) dont les anomalies attendues sont exactement celles voulues."""
    while True:
        rng = random.Random(seed)
        inv, spec = random_invoice(rng, [template])
        if set(spec.expected_issues) == wanted_issues and len(inv.lines) >= 2:
            return inv, spec, rng
        seed += 1


def main() -> None:
    DOCS_IMG.mkdir(parents=True, exist_ok=True)

    # 1. Facture conforme → Factur-X
    inv, spec, rng = _invoice("moderne", set(), seed=4)
    pdf = render_pdf(inv, spec, rng)
    (HERE / "facture_conforme.pdf").write_bytes(pdf)
    res = process(pdf, facturx=True, schematron=True)
    (HERE / "facture_conforme_facturx.pdf").write_bytes(res.facturx_pdf)
    (HERE / "facture_conforme_facturx.xml").write_bytes(res.xml)
    res.report.file = "facture_conforme.pdf"
    (HERE / "rapport_conforme.json").write_text(
        res.report.model_dump_json(indent=2), encoding="utf-8"
    )

    # 2. Facture à corriger : SIREN client et catégorie d'opération absents
    inv, spec, rng = _invoice(
        "classique", {"FR-BUYER-SIREN-MISSING", "FR-OPERATION-CATEGORY-MISSING"}, seed=8
    )
    pdf = render_pdf(inv, spec, rng)
    (HERE / "facture_a_corriger.pdf").write_bytes(pdf)
    res = process(pdf, schematron=True)
    res.report.file = "facture_a_corriger.pdf"
    (HERE / "rapport_a_corriger.json").write_text(
        res.report.model_dump_json(indent=2), encoding="utf-8"
    )
    console = Console(record=True, width=118)
    import facturia.cli as cli

    cli.console = console
    _print_report(res.report)
    console.save_svg(
        str(DOCS_IMG / "cli_rapport.svg"), title="facturia analyze facture_a_corriger.pdf"
    )

    # 3. Facture scannée (OCR)
    inv, spec, rng = _invoice("artisan", set(), seed=15)
    scan = simulate_scan(render_pdf(inv, spec, rng), rng)
    (HERE / "facture_scannee.pdf").write_bytes(scan)
    res = process(scan)
    res.report.file = "facture_scannee.pdf"
    (HERE / "rapport_scannee.json").write_text(
        res.report.model_dump_json(indent=2), encoding="utf-8"
    )

    # Aperçu PNG de la facture à corriger pour le README
    import pdfplumber

    with pdfplumber.open(HERE / "facture_a_corriger.pdf") as doc:
        doc.pages[0].to_image(resolution=90).save(DOCS_IMG / "facture_exemple.png")
    print("exemples régénérés dans", HERE)


if __name__ == "__main__":
    main()
