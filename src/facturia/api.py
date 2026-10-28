"""API HTTP (FastAPI). Documentation interactive : http://localhost:8000/docs"""

from __future__ import annotations

import io
from enum import Enum
from functools import lru_cache
from importlib import resources

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response

from . import __version__
from .pipeline import Decision, Report, process

app = FastAPI(
    title="factur-ia",
    version=__version__,
    description=(
        "Transforme des factures PDF (natives ou scannées) en factures électroniques Factur-X "
        "conformes EN 16931, et contrôle les mentions obligatoires de la réforme française 2026."
    ),
)
MAX_BYTES = 15 * 1024 * 1024


class AnalyzeResult(Report):
    xml: str | None = None


def page_document(fragment: str) -> str:
    """Enveloppe le fragment de l'interface dans un document HTML complet."""
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        "</head><body>" + fragment + "</body></html>"
    )


@lru_cache(maxsize=1)
def demo_page() -> str:
    fragment = resources.files("facturia").joinpath("web/demo.html").read_text(encoding="utf-8")
    return page_document(fragment)


class Backend(str, Enum):
    rules = "rules"
    llm = "llm"
    hybrid = "hybrid"


async def _read_pdf(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Fichier trop volumineux (15 Mo max).")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Le fichier n'est pas un PDF.")
    return data


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def demo() -> str:
    """Interface de démonstration."""
    return demo_page()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/v1/analyze", response_model=AnalyzeResult)
async def analyze(
    file: UploadFile = File(..., description="Facture PDF"),
    backend: Backend = Query(Backend.rules),
    schematron: bool = Query(
        False, description="Valider aussi le XML contre les schematrons EN 16931 et BR-FR"
    ),
    with_xml: bool = Query(False, description="Joindre le XML CII généré à la réponse"),
) -> AnalyzeResult:
    """Extrait les données, contrôle la conformité et renvoie le rapport (décision, anomalies, confiance)."""
    data = await _read_pdf(file)
    result = process(data, extractor=backend.value, schematron=schematron, build_xml=with_xml)
    result.report.file = file.filename
    xml = result.xml.decode("utf-8") if with_xml and result.xml else None
    return AnalyzeResult(**result.report.model_dump(), xml=xml)


@app.post("/v1/preview", responses={200: {"content": {"image/png": {}}}})
async def preview(file: UploadFile = File(..., description="Facture PDF")) -> Response:
    """Image PNG de la première page, pour l'aperçu dans l'interface."""
    import pdfplumber

    data = await _read_pdf(file)
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        image = pdf.pages[0].to_image(resolution=100).original
    out = io.BytesIO()
    image.convert("RGB").save(out, "PNG", optimize=True)
    return Response(content=out.getvalue(), media_type="image/png")


@app.get("/v1/demo/sample/{kind}", responses={200: {"content": {"application/pdf": {}}}})
def demo_sample(kind: str, seed: int = Query(0, ge=0, le=10**6)) -> Response:
    """Facture fictive générée pour la démo : corriger, conforme, scan, inconnue ou hasard."""
    try:
        from .synth import sample_pdf

        pdf = sample_pdf(kind, seed)
    except ImportError as exc:
        raise HTTPException(501, "Installez l'extra « bench » pour générer des exemples.") from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(content=pdf, media_type="application/pdf")


@app.post("/v1/convert", responses={200: {"content": {"application/pdf": {}}}})
async def convert(
    file: UploadFile = File(..., description="Facture PDF"),
    backend: Backend = Query(Backend.rules),
    force: bool = Query(
        False, description="Produire le Factur-X même si la facture n'est pas prête"
    ),
) -> Response:
    """Renvoie le PDF Factur-X (XML CII EN 16931 embarqué). 422 si la facture n'est pas prête."""
    data = await _read_pdf(file)
    result = process(data, extractor=backend.value, facturx=True)
    report = result.report
    if (report.decision != Decision.READY and not force) or result.facturx_pdf is None:
        raise HTTPException(
            422,
            detail={
                "decision": report.decision.value,
                "reasons": report.decision_reasons,
                "issues": [i.model_dump(mode="json") for i in report.issues],
            },
        )
    name = (file.filename or "facture.pdf").rsplit(".", 1)[0] + ".facturx.pdf"
    return Response(
        content=result.facturx_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Facturia-Decision": report.decision.value,
        },
    )
