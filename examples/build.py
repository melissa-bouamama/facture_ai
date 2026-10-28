"""Régénère les exemples du dépôt et la démo statique.

    python examples/build.py

Produit les PDF d'entrée, les rapports JSON et le Factur-X de `examples/`, les images de
`docs/img/` et `docs/demo/index.html`, la version statique de l'interface publiée avec
GitHub Pages (mêmes factures d'exemple que l'application locale, résultats précalculés).
"""

from __future__ import annotations

import base64
import io
import json
import random
import sys
from pathlib import Path

from rich.console import Console

from facturia.cli import _print_report
from facturia.pipeline import process
from facturia.synth import random_invoice, render_pdf, simulate_scan

HERE = Path(__file__).parent
DOCS_IMG = HERE.parent / "docs" / "img"
DEMO_DIR = HERE.parent / "docs" / "demo"
WEB = HERE.parent / "src" / "facturia" / "web" / "demo.html"


def _preview_data_uri(pdf: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        image = doc.pages[0].to_image(resolution=100).original.convert("RGB")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def build_static_demo(fragment_out: Path | None = None) -> Path:
    """Écrit docs/demo/index.html : l'interface avec les résultats des exemples embarqués."""
    from facturia.api import page_document
    from facturia.synth import DEMO_SAMPLES, sample_pdf

    samples = {}
    for kind, label in DEMO_SAMPLES.items():
        pdf = sample_pdf(kind, 0)
        res = process(pdf, schematron=True, build_xml=True)
        res.report.file = f"{label}.pdf"
        samples[kind] = {
            "label": label,
            "report": json.loads(res.report.model_dump_json()),
            "preview": _preview_data_uri(pdf),
            "xml": res.xml.decode("utf-8") if res.xml else None,
        }
    data = json.dumps({"samples": samples}, ensure_ascii=False).replace("</", "<\\/")
    fragment = WEB.read_text(encoding="utf-8").replace(
        '<script id="demo-data" type="application/json">null</script>',
        f'<script id="demo-data" type="application/json">{data}</script>',
    )
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    out = DEMO_DIR / "index.html"
    out.write_text(page_document(fragment), encoding="utf-8")
    if fragment_out:
        fragment_out.write_text(fragment, encoding="utf-8")
    return out


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
    (HERE / "conforme.pdf").write_bytes(pdf)
    res = process(pdf, facturx=True, schematron=True)
    (HERE / "conforme.facturx.pdf").write_bytes(res.facturx_pdf)
    (HERE / "conforme.facturx.xml").write_bytes(res.xml)
    res.report.file = "conforme.pdf"
    (HERE / "conforme.rapport.json").write_text(
        res.report.model_dump_json(indent=2), encoding="utf-8"
    )

    # 2. Facture à corriger : SIREN client et catégorie d'opération absents
    inv, spec, rng = _invoice(
        "classique", {"FR-BUYER-SIREN-MISSING", "FR-OPERATION-CATEGORY-MISSING"}, seed=8
    )
    pdf = render_pdf(inv, spec, rng)
    (HERE / "corriger.pdf").write_bytes(pdf)
    res = process(pdf, schematron=True)
    res.report.file = "corriger.pdf"
    (HERE / "corriger.rapport.json").write_text(
        res.report.model_dump_json(indent=2), encoding="utf-8"
    )
    console = Console(record=True, width=118)
    import facturia.cli as cli

    cli.console = console
    _print_report(res.report)
    console.save_svg(str(DOCS_IMG / "rapport.svg"), title="facturia analyze examples/corriger.pdf")

    # 3. Facture scannée (OCR)
    inv, spec, rng = _invoice("artisan", set(), seed=15)
    scan = simulate_scan(render_pdf(inv, spec, rng), rng)
    (HERE / "scan.pdf").write_bytes(scan)
    res = process(scan)
    res.report.file = "scan.pdf"
    (HERE / "scan.rapport.json").write_text(res.report.model_dump_json(indent=2), encoding="utf-8")

    # Aperçu PNG de la facture à corriger pour le README
    import pdfplumber

    with pdfplumber.open(HERE / "corriger.pdf") as doc:
        doc.pages[0].to_image(resolution=90).save(DOCS_IMG / "facture.png")
    print("exemples régénérés dans", HERE)


if __name__ == "__main__":
    if "--demo-only" not in sys.argv:
        main()
    print("démo statique :", build_static_demo())
