"""Extracteur LLM : sortie JSON contrainte par schéma, via une API compatible OpenAI.

Fonctionne avec un modèle local (Ollama, vLLM, llama.cpp server) comme avec une API
hébergée (Mistral, OpenAI…). Les factures contiennent des données commerciales
sensibles : l'inférence locale est le mode par défaut (`http://localhost:11434/v1`).

Garde-fous contre les hallucinations :
1. sortie JSON validée par un schéma (Pydantic) avec une tentative d'auto-réparation ;
2. *ancrage* : un identifiant, un IBAN ou un montant renvoyé par le modèle n'est
   conservé que s'il apparaît réellement dans le texte du document ;
3. clés de contrôle (Luhn, mod 97) appliquées comme pour l'extracteur à règles.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal

import httpx
from pydantic import BaseModel, ValidationError

from .. import identifiers as ids
from ..models import Address, Invoice, InvoiceLine, OperationCategory, Party, VatBreakdown
from ..normalize import money, parse_amount, parse_date, parse_rate
from ..reader import Document
from .base import CORE_FIELDS, Extraction
from .rules import fold


# ---------------------------------------------------------------- schéma de sortie du LLM
class _Addr(BaseModel):
    line1: str | None = None
    postcode: str | None = None
    city: str | None = None


class _Party(BaseModel):
    name: str | None = None
    siren: str | None = None
    siret: str | None = None
    vat_id: str | None = None
    address: _Addr | None = None


class _Line(BaseModel):
    description: str
    quantity: str | None = None
    unit_price: str | None = None
    net_amount: str | None = None
    vat_rate: str | None = None


class _Vat(BaseModel):
    rate: str
    taxable_amount: str | None = None
    tax_amount: str


class LLMInvoice(BaseModel):
    number: str | None = None
    issue_date: str | None = None
    due_date: str | None = None
    seller: _Party = _Party()
    buyer: _Party = _Party()
    delivery_address: _Addr | None = None
    operation_category: str | None = None
    vat_on_debits: bool = False
    lines: list[_Line] = []
    vat_breakdown: list[_Vat] = []
    total_without_vat: str | None = None
    total_vat: str | None = None
    total_with_vat: str | None = None
    amount_due: str | None = None
    iban: str | None = None
    bic: str | None = None
    payment_terms: str | None = None
    late_penalty_note: str | None = None
    recovery_fee_note: str | None = None
    discount_note: str | None = None


SYSTEM_PROMPT = """Tu extrais les données d'une facture française pour produire une facture électronique EN 16931.
Règles :
- Réponds UNIQUEMENT par un objet JSON conforme au schéma fourni.
- N'invente jamais : si une information n'apparaît pas dans le document, mets null.
- Recopie les identifiants exactement (SIREN 9 chiffres, SIRET 14 chiffres, TVA « FR » + 11 caractères, IBAN).
- Montants et taux : chaînes décimales avec un point (« 1234.56 », « 20 »), sans symbole €.
- Dates au format AAAA-MM-JJ.
- seller = l'émetteur de la facture ; buyer = le client facturé.
- operation_category : « LB » (livraison de biens), « PS » (prestation de services), « LBPS » (mixte),
  uniquement si la catégorie est écrite sur la facture ; sinon null.
- late_penalty_note, recovery_fee_note, discount_note : recopie la phrase correspondante si elle existe.
Le texte est reconstruit depuis la mise en page : « | » sépare des cellules d'une même ligne."""


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5:7b-instruct"
    api_key: str | None = None
    timeout: float = 120.0
    temperature: float = 0.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            base_url=os.getenv("FACTURIA_LLM_BASE_URL", cls.base_url),
            model=os.getenv("FACTURIA_LLM_MODEL", cls.model),
            api_key=os.getenv("FACTURIA_LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        )


class LLMError(RuntimeError):
    pass


class LLMExtractor:
    name = "llm"

    def __init__(self, config: LLMConfig | None = None, client: httpx.Client | None = None):
        self.config = config or LLMConfig.from_env()
        self.client = client or httpx.Client(timeout=self.config.timeout)
        self.last_usage: dict = {}

    # ------------------------------------------------------------------ appel API
    def _chat(self, messages: list[dict], schema_mode: bool = True) -> str:
        payload: dict = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if schema_mode:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "invoice", "schema": LLMInvoice.model_json_schema()},
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        resp = self.client.post(url, json=payload, headers=headers)
        if resp.status_code == 400 and schema_mode:  # serveur sans json_schema : repli json_object
            return self._chat(messages, schema_mode=False)
        if resp.status_code >= 400:
            raise LLMError(f"API LLM {resp.status_code} : {resp.text[:300]}")
        data = resp.json()
        self.last_usage = data.get("usage", {})
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_json(content: str) -> LLMInvoice:
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        return LLMInvoice.model_validate(json.loads(content))

    def ask(self, doc: Document) -> LLMInvoice:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": doc.text},
        ]
        content = self._chat(messages)
        try:
            return self._parse_json(content)
        except (json.JSONDecodeError, ValidationError) as exc:  # une tentative de réparation
            messages += [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": f"JSON invalide ({str(exc)[:300]}). Renvoie uniquement le JSON corrigé.",
                },
            ]
            try:
                return self._parse_json(self._chat(messages))
            except (json.JSONDecodeError, ValidationError) as exc2:
                raise LLMError(f"Sortie LLM inexploitable : {exc2}") from exc2

    # ------------------------------------------------------------------ conversion + ancrage
    def extract(self, doc: Document) -> Extraction:
        raw = self.ask(doc)
        return to_extraction(raw, doc, backend=self.name)


def _grounded_digits(value: str | None, doc_digits: str) -> bool:
    d = ids.digits_only(value)
    return bool(d) and d in doc_digits


def _grounded_amount(value: Decimal | None, doc_digits: str) -> bool:
    if value is None:
        return False
    digits = f"{money(value):.2f}".replace(".", "").lstrip("-")
    return digits in doc_digits or digits.rstrip("0") in doc_digits


def _grounded_text(value: str | None, doc_folded: str) -> bool:
    if not value:
        return False
    tokens = [t for t in re.findall(r"\w{3,}", fold(value))]
    return bool(tokens) and sum(t in doc_folded for t in tokens) / len(tokens) >= 0.6


def to_extraction(raw: LLMInvoice, doc: Document, backend: str = "llm") -> Extraction:
    """Convertit la sortie brute du LLM en `Invoice`, en rejetant ce qui n'est pas ancré."""
    doc_text = doc.text
    doc_digits = ids.digits_only(doc_text.replace(" ", ""))
    doc_folded = fold(doc_text)
    rejected: list[str] = []

    def addr(a: _Addr | None) -> Address:
        a = a or _Addr()
        return Address(line1=a.line1, postcode=a.postcode, city=a.city)

    def party(p: _Party, role: str) -> Party:
        out = Party(
            name=p.name if _grounded_text(p.name, doc_folded) else None, address=addr(p.address)
        )
        siren = ids.digits_only(p.siren)
        if siren and ids.is_valid_siren(siren) and siren in doc_digits:
            out.siren = siren
        elif p.siren:
            rejected.append(f"{role}.siren")
        siret = ids.digits_only(p.siret)
        if siret and ids.is_valid_siret(siret) and siret in doc_digits:
            out.siret = siret
            out.siren = out.siren or siret[:9]
        vat = ids.normalize_vat_id(p.vat_id)
        if (
            vat
            and _grounded_digits(vat, doc_digits)
            and (not vat.startswith("FR") or ids.is_valid_fr_vat(vat))
        ):
            out.vat_id = vat
        elif p.vat_id:
            rejected.append(f"{role}.vat_id")
        return out

    inv = Invoice(
        number=raw.number if raw.number and fold(raw.number) in doc_folded else None,
        issue_date=parse_date(raw.issue_date),
        due_date=parse_date(raw.due_date),
        seller=party(raw.seller, "seller"),
        buyer=party(raw.buyer, "buyer"),
        vat_on_debits=raw.vat_on_debits,
        bic=raw.bic,
        payment_terms=raw.payment_terms,
        late_penalty_note=raw.late_penalty_note
        if _grounded_text(raw.late_penalty_note, doc_folded)
        else None,
        recovery_fee_note=raw.recovery_fee_note
        if _grounded_text(raw.recovery_fee_note, doc_folded)
        else None,
        discount_note=raw.discount_note if _grounded_text(raw.discount_note, doc_folded) else None,
    )
    if raw.number and inv.number is None:
        rejected.append("number")
    if raw.delivery_address:
        a = addr(raw.delivery_address)
        inv.delivery_address = None if a.is_empty() else a
    if raw.operation_category:
        try:
            inv.operation_category = OperationCategory(raw.operation_category.strip().upper())
        except ValueError:
            rejected.append("operation_category")
    iban = ids.normalize_iban(raw.iban)
    if iban and ids.is_valid_iban(iban) and iban[4:] and ids.digits_only(iban[4:]) in doc_digits:
        inv.iban = iban
    elif raw.iban:
        rejected.append("iban")

    for name in ("total_without_vat", "total_vat", "total_with_vat", "amount_due"):
        v = parse_amount(getattr(raw, name))
        if v is not None and _grounded_amount(v, doc_digits):
            setattr(inv, name, money(v))
        elif v is not None:
            rejected.append(name)
    for ln in raw.lines:
        net = parse_amount(ln.net_amount)
        inv.lines.append(
            InvoiceLine(
                description=ln.description.strip(),
                quantity=parse_amount(ln.quantity) or Decimal(1),
                unit_price=money(u) if (u := parse_amount(ln.unit_price)) is not None else None,
                net_amount=money(net) if net is not None else None,
                vat_rate=parse_rate(ln.vat_rate) if ln.vat_rate else None,
            )
        )
    for vb in raw.vat_breakdown:
        rate, tax = parse_rate(vb.rate), parse_amount(vb.tax_amount)
        if rate is None or tax is None:
            continue
        base = parse_amount(vb.taxable_amount)
        inv.vat_breakdown.append(
            VatBreakdown(
                rate=rate,
                taxable_amount=money(base)
                if base is not None
                else money(tax * 100 / rate)
                if rate
                else Decimal(0),
                tax_amount=money(tax),
            )
        )
    if inv.amount_due is None:
        inv.amount_due = inv.total_with_vat

    ex = Extraction(invoice=inv, backend=backend)
    if rejected:
        ex.notes.append(
            "valeurs LLM rejetées (non ancrées ou clé invalide) : " + ", ".join(rejected)
        )
    balanced = None not in (inv.total_without_vat, inv.total_vat, inv.total_with_vat) and (
        money(inv.total_without_vat + inv.total_vat) == money(inv.total_with_vat)
    )
    lines_ok = (
        bool(inv.lines)
        and inv.total_without_vat is not None
        and all(ln.net_amount is not None for ln in inv.lines)
        and money(sum(ln.net_amount for ln in inv.lines)) == inv.total_without_vat
    )
    for f in CORE_FIELDS + [
        "due_date",
        "seller.vat_id",
        "buyer.siren",
        "buyer.vat_id",
        "iban",
        "operation_category",
    ]:
        obj = inv
        for part in f.split("."):
            obj = getattr(obj, part)
        if obj in (None, [], ""):
            continue
        conf = 0.8
        if f in ("seller.siren", "buyer.siren", "seller.vat_id", "buyer.vat_id", "iban"):
            conf = 0.93  # clé de contrôle + ancrage vérifiés
        if f in ("total_without_vat", "total_vat", "total_with_vat"):
            conf = 0.92 if balanced else 0.6
        if f == "lines":
            conf = 0.9 if lines_ok else 0.6
        ex.set(f, conf * (doc.mean_conf if doc.source != "native" else 1.0), "llm+grounded")
    return ex
