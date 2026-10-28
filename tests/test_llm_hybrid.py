"""Tests du LLM et du mode hybride, avec un serveur LLM simulé (httpx.MockTransport)."""

import json
import random

import httpx
import pytest

from facturia.extract.hybrid import HybridExtractor
from facturia.extract.llm import LLMConfig, LLMExtractor
from facturia.models import Invoice
from facturia.pipeline import Decision, process
from facturia.reader import read_pdf
from facturia.synth import HELDOUT_TEMPLATES, SynthSpec, random_invoice, render_pdf


def as_llm_json(inv: Invoice, **overrides) -> str:
    """Ce qu'un LLM parfait répondrait pour cette facture."""
    data = json.loads(inv.model_dump_json())
    data.pop("type_code", None)
    data.pop("currency", None)
    for party in ("seller", "buyer"):
        data[party].pop("email", None)
        data[party]["address"].pop("country_code", None)
        data[party]["address"].pop("line2", None)
    if data["delivery_address"]:
        data["delivery_address"] = {
            k: data["delivery_address"][k] for k in ("line1", "postcode", "city")
        }
    for ln in data["lines"]:
        ln.pop("unit_code", None)
    for vb in data["vat_breakdown"]:
        vb.pop("category", None)
    data.update(overrides)
    return json.dumps(data)


class FakeLLM:
    """Simule /chat/completions et enregistre les requêtes reçues."""

    def __init__(self, *contents: str, status: int = 200, reject_schema: bool = False):
        self.contents = list(contents)
        self.status = status
        self.reject_schema = reject_schema
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "boom"})
        if self.reject_schema and body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": "json_schema unsupported"})
        content = self.contents.pop(0) if len(self.contents) > 1 else self.contents[0]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 400},
            },
        )


def make_llm(fake: FakeLLM) -> LLMExtractor:
    return LLMExtractor(
        LLMConfig(base_url="http://llm.test/v1", model="test"),
        client=httpx.Client(transport=httpx.MockTransport(fake)),
    )


@pytest.fixture
def heldout_invoice():
    rng = random.Random(21)
    inv, spec = random_invoice(rng, HELDOUT_TEMPLATES)
    return inv, render_pdf(inv, spec, rng)


def test_llm_output_is_grounded_in_the_document(heldout_invoice):
    inv, pdf = heldout_invoice
    fake_siren = "418273645"  # clé valide mais absent du document → hallucination
    raw = json.loads(as_llm_json(inv))
    raw["buyer"]["siren"] = fake_siren
    raw["total_with_vat"] = "999999.99"
    fake = FakeLLM(json.dumps(raw))
    ex = make_llm(fake).extract(read_pdf(pdf))
    assert ex.invoice.number == inv.number
    assert ex.invoice.seller.siren == inv.seller.siren
    assert ex.invoice.buyer.siren != fake_siren
    assert ex.invoice.total_with_vat is None
    assert any("SIREN du client" in n and "total TTC" in n for n in ex.notes)
    assert fake.requests[0]["response_format"]["type"] == "json_schema"
    assert fake.requests[0]["temperature"] == 0


def test_llm_falls_back_to_json_object_mode(heldout_invoice):
    inv, pdf = heldout_invoice
    fake = FakeLLM(as_llm_json(inv), reject_schema=True)
    ex = make_llm(fake).extract(read_pdf(pdf))
    assert [r["response_format"]["type"] for r in fake.requests] == ["json_schema", "json_object"]
    assert ex.invoice.total_without_vat == inv.total_without_vat


def test_llm_repairs_invalid_json_once(heldout_invoice):
    inv, pdf = heldout_invoice
    fake = FakeLLM("voici la facture : {pas du json", "```json\n" + as_llm_json(inv) + "\n```")
    ex = make_llm(fake).extract(read_pdf(pdf))
    assert len(fake.requests) == 2
    assert ex.invoice.seller.name == inv.seller.name


def test_hybrid_does_not_call_llm_when_rules_are_confident(complete_invoice):
    spec = SynthSpec("classique", True, True, True, True, True, False, False)
    pdf = render_pdf(complete_invoice, spec, random.Random(0))
    fake = FakeLLM("{}")
    hybrid = HybridExtractor(llm=make_llm(fake))
    report = process(pdf, extractor=hybrid).report
    assert fake.requests == []
    assert report.backend == "hybrid:rules-only"
    assert report.decision == Decision.READY


def test_hybrid_rescues_an_unknown_layout(heldout_invoice):
    inv, pdf = heldout_invoice
    assert process(pdf, extractor="rules").report.decision == Decision.HUMAN_REVIEW
    hybrid = HybridExtractor(llm=make_llm(FakeLLM(as_llm_json(inv))))
    report = process(pdf, extractor=hybrid).report
    assert hybrid.llm_calls == 1
    got = report.invoice
    assert (got.number, got.seller.name, got.buyer.name) == (
        inv.number,
        inv.seller.name,
        inv.buyer.name,
    )
    assert (got.total_without_vat, got.total_with_vat) == (
        inv.total_without_vat,
        inv.total_with_vat,
    )
    assert [ln.net_amount for ln in got.lines] == [ln.net_amount for ln in inv.lines]
    assert report.decision != Decision.HUMAN_REVIEW


def test_hybrid_survives_llm_outage(heldout_invoice):
    _, pdf = heldout_invoice
    hybrid = HybridExtractor(llm=make_llm(FakeLLM("{}", status=500)))
    report = process(pdf, extractor=hybrid).report
    assert report.backend == "hybrid:rules-fallback"
    assert report.decision == Decision.HUMAN_REVIEW
