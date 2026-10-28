"""API HTTP (FastAPI). Documentation interactive : http://localhost:8000/docs"""

from __future__ import annotations

from enum import Enum

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/v1/analyze", response_model=Report)
async def analyze(
    file: UploadFile = File(..., description="Facture PDF"),
    backend: Backend = Query(Backend.rules),
    schematron: bool = Query(
        False, description="Valider aussi le XML contre les schematrons EN 16931 / BR-FR"
    ),
) -> Report:
    """Extrait les données, contrôle la conformité et renvoie le rapport (décision, anomalies, confiance)."""
    data = await _read_pdf(file)
    report = process(data, extractor=backend.value, schematron=schematron).report
    report.file = file.filename
    return report


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
    name = (file.filename or "facture.pdf").rsplit(".", 1)[0] + "_facturx.pdf"
    return Response(
        content=result.facturx_pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Facturia-Decision": report.decision.value,
        },
    )
