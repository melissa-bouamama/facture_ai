import random

from fastapi.testclient import TestClient

from facturia.api import app
from facturia.synth import SynthSpec, render_pdf

client = TestClient(app)


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_analyze_returns_report(sample_pdf):
    pdf, inv, _ = sample_pdf
    r = client.post("/v1/analyze", files={"file": ("f.pdf", pdf, "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["invoice"]["number"] == inv.number
    assert body["decision"] in {"ready", "fix_required", "human_review"}


def test_convert_returns_facturx_for_compliant_invoice(complete_invoice):
    spec = SynthSpec("moderne", True, True, True, True, True, False, False)
    pdf = render_pdf(complete_invoice, spec, random.Random(1))
    r = client.post("/v1/convert", files={"file": ("f.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-facturia-decision"] == "ready"


def test_convert_refuses_non_compliant_invoice(complete_invoice):
    inv = complete_invoice.model_copy(update={"operation_category": None})
    spec = SynthSpec("classique", True, False, True, True, True, False, False)
    pdf = render_pdf(inv, spec, random.Random(2))
    r = client.post("/v1/convert", files={"file": ("f.pdf", pdf, "application/pdf")})
    assert r.status_code == 422
    assert "FR-OPERATION-CATEGORY-MISSING" in {i["code"] for i in r.json()["detail"]["issues"]}


def test_rejects_non_pdf():
    r = client.post("/v1/analyze", files={"file": ("f.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_demo_page_is_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert r.text.startswith("<!doctype html>")
    assert 'id="demo-data"' in r.text


def test_demo_samples_preview_and_xml():
    pdf = client.get("/v1/demo/sample/corriger").content
    assert pdf.startswith(b"%PDF")
    r = client.post("/v1/preview", files={"file": ("f.pdf", pdf, "application/pdf")})
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    r = client.post(
        "/v1/analyze?schematron=true&with_xml=true",
        files={"file": ("f.pdf", pdf, "application/pdf")},
    )
    body = r.json()
    assert body["decision"] == "fix_required"
    assert body["xml"].startswith("<?xml")
    assert body["schematrons_run"] == ["en16931", "br-fr"]
    assert client.get("/v1/demo/sample/inexistant").status_code == 404
