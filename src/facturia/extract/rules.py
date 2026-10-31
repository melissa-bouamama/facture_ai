"""Extracteur déterministe, guidé par la mise en page.

Principe : on repère des *libellés* (« Facture n° », « Total HT », « Facturé à »…) dans
les segments reconstruits par `reader`, puis on cherche la valeur au bon endroit :
dans le même segment, dans la cellule à droite, ou juste en dessous. Les identifiants
sont acceptés seulement si leur clé de contrôle est correcte, et les lignes du tableau
seulement si quantité × prix unitaire = montant.

Cet extracteur est rapide (quelques ms), explicable et sans coût d'inférence. Il sert de
référence et de premier étage au mode hybride, qui n'appelle un LLM que si la
validation révèle un doute.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .. import identifiers as ids
from ..models import Address, Invoice, InvoiceLine, OperationCategory, VatBreakdown
from ..normalize import AMOUNT_RE, find_dates, money, parse_amount, parse_rate
from ..reader import Document, Line, Segment
from .base import Extraction


def fold(text: str) -> str:
    """Minuscules sans accents, en conservant la longueur (positions alignées)."""
    out = []
    for ch in text:
        base = unicodedata.normalize("NFKD", ch)[:1]
        out.append(base.lower() if base else ch.lower())
    return "".join(out)


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


L_NUMBER = _rx(
    r"(?:n[°o]\s*(?:de\s*)?facture|num[eé]ro\s*(?:de\s*)?facture|facture\s*(?:n[°o]|no\b\.?|num[eé]ro|#)|invoice\s*(?:n[°o]|#|number))\s*[:.]?"
)
L_DUE = _rx(
    r"(?:date\s*d.?\s*)?[eé]ch[eé]ance|date\s*limite(?:\s*de\s*paiement)?|[aà]\s*r[eé]gler\s*avant(?:\s*le)?|payable\s*(?:avant\s*)?le"
)
L_ISSUE = _rx(
    r"date\s*(?:de\s*facture|de\s*facturation|d.?\s*[eé]mission|facture)?|[eé]mise?\s*le|fait\s*le"
)
L_BUYER = _rx(
    r"^(?:factur[eé]e?\s*[aà]|client|destinataire|adresse\s*de\s*facturation|acheteur)\s*:?\s*"
)
L_DELIVERY = _rx(
    r"^(?:adresse\s*de\s*livraison|livr[eé]e?\s*[aà]|lieu\s*de\s*livraison|livraison)\s*:?\s*"
)
L_HT = _rx(r"(?:sous[- ]?)?total\s*h\.?\s*t\b|montant\s*h\.?\s*t\b|total\s*hors\s*tax")
L_TVA_RATE = _rx(
    r"(?:t\.?\s*v\.?\s*a\.?|montant\s*tva)\s*(?:[aà]\s*)?\(?(\d{1,2}(?:[.,]\d{1,2})?)\s*%"
)
L_TVA_TOTAL = _rx(r"total\s*t\.?\s*v\.?\s*a|montant\s*(?:total\s*)?(?:de\s*la\s*)?tva\b(?!\s*\d)")
L_TTC = _rx(r"total\s*t\.?\s*t\.?\s*c|montant\s*t\.?\s*t\.?\s*c|toutes\s*taxes\s*comprises")
L_DUE_AMOUNT = _rx(
    r"net\s*[aà]\s*payer|reste\s*[aà]\s*payer|montant\s*[aà]\s*r[eé]gler|solde\s*d[uû]|^solde\b"
)
# Raison sociale annoncée par un libellé (« Nom de la société : Tilleuls Hôtellerie »), fréquent sur les
# factures produites par des logiciels de gestion (hôtellerie, caisse, ERP).
L_SELLER_NAME = _rx(
    r"^(?:nom\s*de\s*(?:la\s*)?soci[eé]t[eé]|raison\s*sociale|d[eé]nomination(?:\s*sociale)?)\s*[:.]?\s*"
)
# Numéro porté par le titre lui-même : « FACTURE 2025117 », « Facture n° FA-12 ».
RX_TITLE_NUMBER = _rx(
    r"^(?:facture|invoice)\s*(?:n[°o]\.?\s*)?[:#]?\s*([a-z0-9][\w\-/.]*\d[\w\-/]*)\s*$"
)
H_DESC = _rx(r"d[eé]signation|description|libell[eé]|article|prestation")
H_AMOUNT = _rx(r"total|montant")
H_QTY = _rx(r"quantit[eé]|\bqt[eé]s?\b|\bqte\b")
H_PRICE = _rx(r"\bprix|\bp\.?\s*u\b|unitaire")
# Cellule de TVA par unité suivie du taux : « 5,00 € (10%) »
RX_VAT_IN_CELL = re.compile(r"^\s*[\d\s.,]*\s*€?\s*\(\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%\s*\)\s*$")
RX_DATE_CELL = re.compile(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")
RX_LONG_DIGITS = re.compile(r"(?<![\d])(\d(?:\s?\d){12,14})(?![\d])")

RX_SIRET = re.compile(r"(?<!\d)(\d{3}\s?\d{3}\s?\d{3}\s?\d{5})(?!\d)")
RX_SIREN = re.compile(r"(?<![\d\w])(\d{3}\s?\d{3}\s?\d{3})(?![\d])")
RX_VAT = re.compile(r"\b(FR(?:\s?[0-9A-Z]){2}(?:\s?\d){9})\b")
RX_IBAN = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?)")
RX_BIC = re.compile(r"\bBIC\s*:?\s*([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b")
RX_POSTCODE_CITY = re.compile(r"\b(\d{5})\s+([A-Za-zÀ-ÿ'’\- ]{2,40}?)\s*$")
RX_REF = re.compile(r"^[A-Z]{1,4}[-_]?\d{2,}\s+")
ID_CONTEXT = _rx(r"\b(?:siren|siret|rcs|r\.c\.s|tva|vat)\b")

# Confusions OCR fréquentes dans les zones numériques (O/0, I/l/1, S/5, B/8).
_OCR_DIGIT = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})
_TOL = r"[0-9OoIlSB]"
RX_ID_TOLERANT = re.compile(
    rf"(?<![\w])(FR\s?[0-9A-Z]{{2}}\s?|)({_TOL}{{3}}\s?{_TOL}{{3}}\s?{_TOL}{{3}}(?:\s?{_TOL}{{5}})?)(?![\w])"
)


def is_ocr_noise(text: str, conf: float) -> bool:
    """Cellule parasite produite par le bruit d'un scan : symbole isolé ou mot court peu sûr."""
    if not any(c.isalnum() for c in text):
        return True
    if len(text) == 1 and not text.isdigit():  # lettre isolée dans sa propre cellule
        return True
    return len(text) <= 4 and conf < 0.75


def clean_ocr_text(text: str) -> str:
    """Corrige les accolades lues à la place de parenthèses : « (lot de 12} » → « (lot de 12) »."""
    if "(" in text and "}" in text and "{" not in text:
        text = text.replace("}", ")")
    if ")" in text and "{" in text and "}" not in text:
        text = text.replace("{", "(")
    return text


def repair_ocr_ids(text: str) -> str:
    """Corrige les confusions lettre/chiffre dans les identifiants, si la clé de contrôle le confirme.

    « FRO7552813248 » (O lu à la place de 0) devient « FR07552813248 » parce que la clé
    corrigée est valide. Une chaîne qui ne passe pas la clé est laissée telle quelle.
    """

    def fix(m: re.Match) -> str:
        prefix, body = m.group(1), m.group(2)
        if sum(c.isdigit() for c in body) < 7:
            return m.group(0)
        body_fixed = body.translate(_OCR_DIGIT)
        if prefix:
            key = prefix[2:].strip()
            key_fixed = key.translate(_OCR_DIGIT) if not key.isdigit() else key
            candidate = "FR" + key_fixed + ids.digits_only(body_fixed)
            if ids.is_valid_fr_vat(candidate) and (candidate[2:4].isdigit() or key == key_fixed):
                return candidate
            return m.group(0)
        digits = ids.digits_only(body_fixed)
        ok = ids.is_valid_siren(digits) if len(digits) == 9 else ids.is_valid_siret(digits)
        return body_fixed if ok and body_fixed != body else m.group(0)

    return RX_ID_TOLERANT.sub(fix, text)


@dataclass
class _Pos:
    line: int
    seg: int


class RulesExtractor:
    name = "rules"

    def extract(self, doc: Document) -> Extraction:
        self.doc = doc
        self.lines: list[Line] = doc.lines
        self.ocr_factor = doc.mean_conf if doc.source != "native" else 1.0
        inv = Invoice()
        ex = Extraction(invoice=inv, backend=self.name)

        self._header(inv, ex)
        buyer_rng, delivery_rng = self._parties(inv, ex)
        self._identifiers(inv, ex, buyer_rng, delivery_rng)
        self._table(inv, ex)
        self._totals(inv, ex)
        self._payment_and_mentions(inv, ex)
        self._reconcile(inv, ex)
        return ex

    # ------------------------------------------------------------------ helpers
    def _conf(self, base: float) -> float:
        return base * self.ocr_factor

    def _find_label(self, rx: re.Pattern, start: int = 0, exclude: re.Pattern | None = None):
        for i in range(start, len(self.lines)):
            for j, seg in enumerate(self.lines[i].segments):
                m = rx.search(fold(seg.text))
                if m and not (exclude and exclude.search(fold(seg.text))):
                    yield _Pos(i, j), seg, m

    def _value_near(self, pos: _Pos, m: re.Match, parser):
        """Valeur après le libellé : même segment, cellule à droite, puis ligne suivante."""
        line = self.lines[pos.line]
        seg = line.segments[pos.seg]
        rest = seg.text[m.end() :].strip(" :.-\t")
        if rest:
            v = parser(rest)
            if v is not None:
                return v, "same"
        if pos.seg + 1 < len(line.segments):
            v = parser(line.segments[pos.seg + 1].text)
            if v is not None:
                return v, "right"
        # Valeur à droite mais légèrement décalée vers le bas (police différente du libellé) :
        # la reconstruction l'a placée sur la ligne suivante, avant la cellule voisine.
        if pos.line + 1 < len(self.lines):
            below = self.lines[pos.line + 1]
            limit = (
                line.segments[pos.seg + 1].x0 if pos.seg + 1 < len(line.segments) else float("inf")
            )
            if below.top - seg.top <= 0.8 * max(seg.bottom - seg.top, 6.0):
                for s in below.segments:
                    if seg.x1 - 2 <= s.x0 and s.x1 <= limit + 2:
                        v = parser(s.text)
                        if v is not None:
                            return v, "right"
        if pos.line + 1 < len(self.lines):
            for s in self.lines[pos.line + 1].segments:
                if s.x0 <= seg.x1 + 5 and s.x1 >= seg.x0 - 5:
                    v = parser(s.text)
                    if v is not None:
                        return v, "below"
        return None, None

    # ------------------------------------------------------------------ en-tête
    def _header(self, inv: Invoice, ex: Extraction) -> None:
        def parse_number(text: str) -> str | None:
            cand = text.strip().split("  ")[0].strip()
            cand = re.split(r"\s+(?:du|date|le)\b", cand, flags=re.IGNORECASE)[0].strip()
            if (
                3 <= len(cand) <= 35
                and re.search(r"\d", cand)
                and re.fullmatch(r"[A-Za-z0-9][\w\-/. ]*", cand)
            ):
                return cand
            return None

        for pos, _seg, m in self._find_label(L_NUMBER):
            v, how = self._value_near(pos, m, parse_number)
            if v:
                inv.number = v
                ex.set("number", self._conf(0.95 if how == "same" else 0.9), f"rules:label-{how}")
                break
        if inv.number is None:  # numéro dans le titre : « FACTURE 2025117 »
            for ln in self.lines[:6]:
                for seg in ln.segments:
                    m = RX_TITLE_NUMBER.match(fold(seg.text).strip())
                    if m:
                        start = len(seg.text) - len(seg.text.lstrip())
                        inv.number = seg.text[start + m.start(1) : start + m.end(1)]
                        ex.set("number", self._conf(0.85), "rules:title")
                        break
                if inv.number:
                    break

        def parse_d(text: str) -> date | None:
            ds = find_dates(text)
            return ds[0] if ds else None

        for pos, _seg, m in self._find_label(L_DUE):
            v, how = self._value_near(pos, m, parse_d)
            if v:
                inv.due_date = v
                ex.set("due_date", self._conf(0.9), f"rules:label-{how}")
                break

        # « Date : 06/09 | Date limite de paiement : 21/09 » peut tenir dans un seul segment :
        # on examine chaque occurrence du libellé et on écarte celles qui annoncent l'échéance.
        not_issue = _rx(
            r"^date\s*(?:d.?\s*)?(?:ech[eé]ance|limite|de\s*livraison|de\s*paiement|de\s*naissance)"
        )
        found = False
        for i, ln in enumerate(self.lines):
            for j, seg in enumerate(ln.segments):
                ft = fold(seg.text)
                for m in L_ISSUE.finditer(ft):
                    if not_issue.match(ft[m.start() :]):
                        continue
                    v, how = self._value_near(_Pos(i, j), m, parse_d)
                    if v and v != inv.due_date:
                        inv.issue_date = v
                        ex.set("issue_date", self._conf(0.9), f"rules:label-{how}")
                        found = True
                        break
                if found:
                    break
            if found:
                break
        if inv.issue_date is None:  # repli : première date du document
            for d in find_dates(self.doc.text):
                if d != inv.due_date:
                    inv.issue_date = d
                    ex.set("issue_date", self._conf(0.5), "rules:fallback-first-date")
                    break

        cn = _rx(r"\bavoir\b|credit\s*note")
        if any(cn.search(fold(ln.text)) for ln in self.lines[:12]):
            inv.type_code = "381"

    # ------------------------------------------------------------------ parties
    def _is_label(self, seg: Segment) -> bool:
        t = fold(seg.text)
        return (
            any(
                rx.search(t)
                for rx in (L_NUMBER, L_DUE, L_BUYER, L_DELIVERY, L_HT, L_TTC, L_SELLER_NAME)
            )
            or (bool(H_DESC.search(t)) and len(t) < 25)
            or bool(re.match(r"^date\b", t))
            or bool(re.match(r"^cat[eé]gorie", t))
        )

    def _collect_block(
        self, line_idx: int, anchor: Segment, first_text: str | None, max_lines: int = 7
    ):
        """Rassemble les segments alignés sous `anchor` (même colonne, lignes contiguës)."""
        texts = [first_text] if first_text else []
        self._block_conf = {first_text: anchor.conf} if first_text else {}
        last_bottom = anchor.bottom
        height = max(anchor.bottom - anchor.top, 6.0)
        end = line_idx
        for i in range(line_idx + 1, min(line_idx + 1 + max_lines, len(self.lines))):
            cand = [s for s in self.lines[i].segments if abs(s.x0 - anchor.x0) <= 14]
            if not cand:
                # ligne d'une autre colonne intercalée (ex. une date un peu plus basse que son
                # libellé) : on continue, l'écart vertical ci-dessous borne toujours le bloc
                continue
            s = cand[0]
            if s.top - last_bottom > 1.9 * height or self._is_label(s):
                break
            texts.append(s.text)
            self._block_conf[s.text] = s.conf
            last_bottom = s.bottom
            end = i
        return texts, (line_idx, end)

    @staticmethod
    def _parse_block(texts: list[str]) -> tuple[str | None, Address]:
        addr = Address()
        name = None
        rest = []
        for t in texts:
            t = t.strip()
            if (
                not t
                or ID_CONTEXT.search(fold(t))
                or re.match(r"^(t[eé]l|tel|fax|e-?mail|www)", fold(t))
            ):
                continue
            if name is None:
                name = t
                continue
            rest.append(t)
        for t in rest:
            # « 12 rue X, 75011 Paris » ou « 12 rue X - 75011 Paris » ou « 75011 Paris »
            m = RX_POSTCODE_CITY.search(t)
            if m:
                addr.postcode, addr.city = m.group(1), m.group(2).strip()
                before = t[: m.start()].strip(" ,-–")
                if before:
                    addr.line1 = addr.line1 or before
            elif addr.line1 is None:
                addr.line1 = t
            elif addr.postcode is None:
                addr.line2 = t
        if name and RX_POSTCODE_CITY.search(name) and not rest:  # bloc d'une seule ligne
            name = None
        return name, addr

    def _parties(self, inv: Invoice, ex: Extraction):
        buyer_rng = delivery_rng = None
        for pos, seg, m in self._find_label(L_BUYER):
            first = seg.text[m.end() :].strip() or None
            texts, buyer_rng = self._collect_block(pos.line, seg, first)
            name, addr = self._parse_block(texts)
            if name:
                inv.buyer.name, inv.buyer.address = name, addr
                # confiance OCR du segment lui-même : un nom mal lu (« lropharm ») doit être revu
                ex.set(
                    "buyer.name", 0.9 * self._block_conf.get(name, self.ocr_factor), "rules:block"
                )
                break
        for pos, seg, m in self._find_label(L_DELIVERY):
            first = seg.text[m.end() :].strip() or None
            texts, delivery_rng = self._collect_block(pos.line, seg, first)
            _, addr = self._parse_block(texts)
            if not addr.is_empty():
                inv.delivery_address = addr
            break

        # Vendeur : bloc en haut à gauche de la première page (en ignorant le titre « FACTURE »)
        top_name, top_conf = None, self.ocr_factor
        for i, ln in enumerate(self.lines[:3]):
            segs = [s for s in ln.segments if not self._is_title(s.text)]
            if not segs:
                continue
            first_seg = min(segs, key=lambda s: s.x0)
            if self._is_label(first_seg) or (buyer_rng and buyer_rng[0] <= i <= buyer_rng[1]):
                break
            texts, _ = self._collect_block(i, first_seg, first_seg.text)
            name, addr = self._parse_block(texts)
            if name and not L_NUMBER.search(fold(name)):
                top_name = name
                top_conf = self._block_conf.get(name, self.ocr_factor)
                inv.seller.address = addr
            break
        # Raison sociale annoncée par un libellé : prioritaire sur le bloc du haut (souvent un logo)
        labeled = None
        for pos, _seg, m in self._find_label(L_SELLER_NAME):
            if buyer_rng and buyer_rng[0] <= pos.line <= buyer_rng[1]:
                continue
            labeled, how = self._value_near(pos, m, self._parse_name)
            if labeled:
                inv.seller.name = labeled
                ex.set("seller.name", self._conf(0.9), f"rules:label-{how}")
                return buyer_rng, delivery_rng

        # Recoupement avec le pied de page légal (raison sociale + RCS) : la source la plus fiable
        footer_name = self._footer_name()
        same = (
            top_name
            and footer_name
            and " ".join(fold(top_name).split()) == " ".join(fold(footer_name).split())
        )
        if same:
            inv.seller.name = top_name
            ex.set("seller.name", 0.97 * max(top_conf, self.ocr_factor), "rules:top-block+footer")
        elif top_name and footer_name:
            text = fold(self.doc.text)
            pick = max((footer_name, top_name), key=lambda n: text.count(fold(n)))
            inv.seller.name = pick
            ex.set("seller.name", self._conf(0.7), "rules:conflict")
        elif top_name or footer_name:
            inv.seller.name = top_name or footer_name
            ex.set(
                "seller.name",
                0.8 * top_conf if top_name else self._conf(0.75),
                "rules:top-block" if top_name else "rules:footer",
            )
        return buyer_rng, delivery_rng

    @staticmethod
    def _is_title(text: str) -> bool:
        t = fold(text).strip()
        return re.sub(r"[\s.]", "", t) in {
            "facture",
            "invoice",
            "avoir",
            "factured'avoir",
            "devis",
        } or bool(RX_TITLE_NUMBER.match(t))

    def _parse_name(self, text: str) -> str | None:
        """Valeur plausible pour une raison sociale : du texte, pas un libellé ni un nombre."""
        t = text.strip(" :.-\t")
        if not 2 <= len(t) <= 80 or sum(c.isalpha() for c in t) < 2:
            return None
        if any(rx.search(fold(t)) for rx in (L_SELLER_NAME, L_BUYER, L_NUMBER, ID_CONTEXT)):
            return None
        return t

    def _footer_name(self) -> str | None:
        for ln in reversed(self.lines):
            t = ln.text
            if re.search(r"\bRCS\b|R\.C\.S|capital", t):
                name = re.split(r"\s+[-–]\s+|,\s*(?:capital|SAS|SARL)|\s+au\s+capital", t)[
                    0
                ].strip()
                if 2 < len(name) < 80 and not re.search(r"\d{5}", name):
                    return name
        return None

    # ------------------------------------------------------------------ identifiants
    def _identifiers(self, inv: Invoice, ex: Extraction, buyer_rng, delivery_rng) -> None:
        def in_rng(i, rng):
            return rng is not None and rng[0] <= i <= rng[1]

        seller_sirens: list[tuple[str, float]] = []
        bad_siret = None
        for i, ln in enumerate(self.lines):
            prev_ft = ""
            for seg in ln.segments:
                t = repair_ocr_ids(seg.text)
                ft = fold(t)
                label_ft, prev_ft = prev_ft, ft  # libellé éventuel dans la cellule de gauche
                if "iban" in ft or "bic" in ft:
                    continue
                buyer_side = in_rng(i, buyer_rng) or in_rng(i, delivery_rng)
                for m in RX_VAT.finditer(t.upper()):
                    vat = ids.normalize_vat_id(m.group(1))
                    if ids.is_valid_fr_vat(vat):
                        party = inv.buyer if buyer_side else inv.seller
                        if party.vat_id is None:
                            party.vat_id = vat
                            ex.set(
                                f"{'buyer' if buyer_side else 'seller'}.vat_id",
                                self._conf(0.95),
                                "rules:checksum",
                            )
                if not (ID_CONTEXT.search(ft) or ID_CONTEXT.search(label_ft)):
                    continue
                if "siret" in ft + " " + label_ft and not buyer_side and bad_siret is None:
                    # SIRET imprimé avec un mauvais nombre de chiffres ou une clé fausse
                    for m in RX_LONG_DIGITS.finditer(t):
                        digits = ids.digits_only(m.group(1))
                        if not ids.is_valid_siret(digits):
                            bad_siret = digits
                for m in RX_SIRET.finditer(t):
                    siret = ids.digits_only(m.group(1))
                    if ids.is_valid_siret(siret):
                        party = inv.buyer if buyer_side else inv.seller
                        party.siret = party.siret or siret
                        if not buyer_side:
                            seller_sirens.append((siret[:9], 0.95))
                        elif inv.buyer.siren is None:
                            inv.buyer.siren = siret[:9]
                            ex.set("buyer.siren", self._conf(0.95), "rules:siret")
                t_wo_siret = RX_SIRET.sub(" ", t)
                t_wo_siret = RX_VAT.sub(" ", t_wo_siret.upper())
                for m in RX_SIREN.finditer(t_wo_siret):
                    siren = ids.digits_only(m.group(1))
                    if not ids.is_valid_siren(siren):
                        continue
                    if buyer_side:
                        if inv.buyer.siren is None:
                            inv.buyer.siren = siren
                            ex.set("buyer.siren", self._conf(0.95), "rules:checksum")
                    else:
                        seller_sirens.append((siren, 0.95))
        if inv.seller.siret is None and bad_siret:
            inv.seller.siret = bad_siret  # signalé par la validation, jamais exporté
        # SIREN implicite dans le n° de TVA
        if inv.seller.vat_id and ids.is_valid_fr_vat(inv.seller.vat_id):
            seller_sirens.append((inv.seller.vat_id[-9:], 0.85))
        if inv.buyer.siren is None and inv.buyer.vat_id and ids.is_valid_fr_vat(inv.buyer.vat_id):
            inv.buyer.siren = inv.buyer.vat_id[-9:]
            ex.set("buyer.siren", self._conf(0.85), "rules:from-vat")
        if seller_sirens:
            # le SIREN le plus fréquemment cité (pied de page, SIRET, TVA) l'emporte
            counts: dict[str, int] = {}
            for s, _ in seller_sirens:
                counts[s] = counts.get(s, 0) + 1
            best = max(counts, key=counts.get)
            inv.seller.siren = best
            agree = counts[best] >= 2
            ex.set(
                "seller.siren",
                self._conf(0.97 if agree else 0.85),
                "rules:checksum" + ("+agree" if agree else ""),
            )

    # ------------------------------------------------------------------ tableau
    def _table(self, inv: Invoice, ex: Extraction) -> None:
        header_idx = None
        has_ref = False
        for i, ln in enumerate(self.lines):
            t = fold(ln.text)
            classic = H_DESC.search(t) and H_AMOUNT.search(t) and len(ln.segments) >= 2
            # tableau sans colonne de désignation : « Prix HT | Quantité | Total »
            priced = (H_QTY.search(t) and H_PRICE.search(t) and H_AMOUNT.search(t)) and len(
                ln.segments
            ) >= 3
            if classic or priced:
                header_idx = i
                has_ref = bool(re.search(r"\bref", t))
                break
        if header_idx is None:
            ex.notes.append("tableau des lignes non trouvé")
            return
        header_text = fold(self.lines[header_idx].text)
        has_vat_col = bool(re.search(r"\btva\b|\btaux\b", header_text))
        # Colonnes TTC (prix ou total) : les rôles se lisent dans l'en-tête, sinon on
        # confondrait le prix TTC et la quantité, dont le produit donne aussi le total.
        anchors = self._header_anchors(self.lines[header_idx]) if "ttc" in header_text else []
        caption = self._caption_above(header_idx)

        rows: list[InvoiceLine] = []
        pending_desc: list[str] = []
        checks_ok = 0
        prev_bottom = self.lines[header_idx].bottom
        for ln in self.lines[header_idx + 1 :]:
            t = fold(ln.text)
            if L_HT.search(t) or L_TTC.search(t) or re.match(r"^(total|sous-total|montant)\b", t):
                break
            desc, nums, rate = self._split_row(ln, has_ref)
            if not nums:
                if desc:
                    if rows and not pending_desc and ln.top - prev_bottom < 14:
                        rows[-1].description += " " + desc
                    else:
                        pending_desc.append(desc)
                prev_bottom = ln.bottom
                continue
            parsed = (self._parse_by_roles(ln, anchors, rate) if anchors else None) or (
                self._parse_numbers(nums)
            )
            if parsed is None:
                prev_bottom = ln.bottom
                continue
            qty, unit, net, ok = parsed
            description = " ".join(pending_desc + ([desc] if desc else [])).strip()
            pending_desc = []
            if not description and not rows and caption:
                # désignation écrite au-dessus du tableau : « Hébergement 112 (du … au …) »
                description, caption = caption, None
            if not description:
                continue
            rows.append(
                InvoiceLine(
                    description=description,
                    quantity=qty,
                    unit_price=unit,
                    net_amount=net,
                    vat_rate=rate if has_vat_col or rate else None,
                )
            )
            checks_ok += ok
            prev_bottom = ln.bottom
        if rows:
            inv.lines = rows
            ratio = checks_ok / len(rows)
            ex.set("lines", self._conf(0.6 + 0.35 * ratio), "rules:table+arith")

    @staticmethod
    def _split_row(ln: Line, has_ref: bool) -> tuple[str, list[str], Decimal | None]:
        """Sépare la désignation (texte) des cellules numériques d'une ligne de tableau."""
        desc_parts, nums = [], []
        rate = None
        for seg in ln.segments:
            text = seg.text.strip()
            if is_ocr_noise(text, seg.conf):
                continue
            m_rate = re.fullmatch(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", text)
            if m_rate:
                rate = parse_rate(text)
                continue
            m_vat = RX_VAT_IN_CELL.match(text)
            if m_vat:  # montant de TVA unitaire et taux : on ne garde que le taux
                rate = parse_rate(m_vat.group(1) + "%")
                continue
            if RX_DATE_CELL.match(text):  # date de prestation, pas une désignation
                continue
            if re.fullmatch(r"[\d\s.,€]+(?:EUR)?", text) and re.search(r"\d", text):
                nums.append(text)
                continue
            # cellule mixte (OCR) : « Désignation 2 620,00 20 % »
            m = re.search(r"((?:\s+\d[\d\s.,]*(?:\s*%)?)+)$", text)
            if m and nums == [] and len(text) - len(m.group(1)) > 3:
                head, tail = text[: m.start()], m.group(1)
                desc_parts.append(head)
                for tok in re.findall(
                    r"\d{1,2}(?:[.,]\d{1,2})?\s*%|[\d][\d.,]*(?:\s\d{3})*(?:[.,]\d{2})?", tail
                ):
                    if tok.endswith("%"):
                        rate = parse_rate(tok)
                    else:
                        nums.append(tok)
                continue
            desc_parts.append(text)
        desc = clean_ocr_text(" ".join(desc_parts).strip())
        if has_ref:
            desc = RX_REF.sub("", desc)
        return desc, nums, rate

    @staticmethod
    def _parse_numbers(cells: list[str]):
        """Interprète les cellules numériques : [qté], [PU], montant. Vérifie qté × PU."""
        values = []
        for c in cells:
            v = parse_amount(c)
            if v is not None:
                values.append((c, v))
        if not values:
            return None
        net = values[-1][1]
        if len(values) >= 3:
            qty, unit = values[-3][1], values[-2][1]
            if money(qty * unit) == money(net):
                return qty, unit, money(net), 1
        if len(values) >= 2:
            # cellule fusionnée « 10 450,00 » = qté 10 + PU 450,00 ?
            raw = values[-2][0]
            parts = raw.split()
            if len(parts) >= 2:
                qty_c, unit_c = parse_amount(parts[0]), parse_amount("".join(parts[1:]))
                if qty_c and unit_c and money(qty_c * unit_c) == money(net):
                    return qty_c, unit_c, money(net), 1
            unit = values[-2][1]
            if unit and money(unit) == money(net):
                return Decimal(1), unit, money(net), 1
            if unit:
                q = (net / unit).quantize(Decimal("0.001"))
                if money(q * unit) == money(net):
                    return q.normalize(), unit, money(net), 1
        return Decimal(1), None, money(net), 0

    @staticmethod
    def _header_anchors(ln: Line) -> list[tuple[str, float]]:
        """Rôle et position horizontale de chaque colonne, lus mot à mot dans l'en-tête.

        On travaille au niveau du mot car l'OCR fusionne parfois deux en-têtes voisins
        dans une même cellule (« PRIX TTC QUANTITÉ »).
        """
        words = sorted((w for s in ln.segments for w in s.words), key=lambda w: w.x0)
        anchors: list[tuple[str, float]] = []
        i = 0
        while i < len(words):
            t = fold(words[i].text).strip(".:")
            nxt = fold(words[i + 1].text) if i + 1 < len(words) else ""
            role, span = None, 1
            if re.match(r"prix|p\.?u\b|tarif", t):
                role = "unit_ttc" if nxt.startswith("ttc") else "unit_ht"
                span = 2 if nxt.startswith(("ttc", "ht", "unit")) else 1
            elif re.match(r"quantit|qte|qt\b", t):
                role = "qty"
            elif re.match(r"total|montant", t):
                role = {"ttc": "total_ttc", "ht": "total_ht"}.get(nxt[:3].strip(), "total")
                span = 2 if role != "total" else 1
            elif t in ("tva", "taux"):
                role = "vat"
            if role:
                last = words[i + span - 1]
                anchors.append((role, (words[i].x0 + last.x1) / 2))
            i += span
        return anchors

    @staticmethod
    def _parse_by_roles(ln: Line, anchors: list[tuple[str, float]], rate: Decimal | None):
        """Ligne d'un tableau à colonnes TTC : chaque nombre prend le rôle de la colonne la
        plus proche. Le montant HT est recalculé (quantité × prix HT) et vérifié."""
        cells: dict[str, Decimal] = {}
        for seg in ln.segments:
            text = seg.text.strip()
            if is_ocr_noise(text, seg.conf) or RX_VAT_IN_CELL.match(text):
                continue
            if not (re.fullmatch(r"[\d\s.,€]+(?:EUR)?", text) and re.search(r"\d", text)):
                continue
            value = parse_amount(text)
            if value is None:
                continue
            center = (seg.x0 + seg.x1) / 2
            role = min(anchors, key=lambda a: abs(a[1] - center))[0]
            cells.setdefault(role, value)
        qty = cells.get("qty")
        total = next((cells[r] for r in ("total", "total_ttc", "total_ht") if r in cells), None)
        unit_ht, unit_ttc = cells.get("unit_ht"), cells.get("unit_ttc")
        if qty is None or total is None:
            return None
        if (
            unit_ht is not None
            and money(qty * unit_ht) == money(total)
            and "total_ttc" not in cells
        ):
            return qty, unit_ht, money(total), 1
        if unit_ttc is not None and money(qty * unit_ttc) == money(total):  # total TTC
            if unit_ht is None and rate:
                unit_ht = money(unit_ttc * 100 / (100 + rate))
            if unit_ht is not None and (
                rate is None
                or abs(money(unit_ht * (100 + rate) / 100) - unit_ttc) <= Decimal("0.01")
            ):
                return qty, unit_ht, money(qty * unit_ht), 1
        return None

    def _caption_above(self, header_idx: int) -> str | None:
        """Désignation écrite juste au-dessus du tableau, quand le tableau n'en a pas."""
        header = self.lines[header_idx]
        for k in range(header_idx - 1, max(-1, header_idx - 4), -1):
            ln = self.lines[k]
            if header.top - ln.bottom > 60:
                break
            if len(ln.segments) != 1:
                continue
            seg = ln.segments[0]
            text = seg.text.strip()
            if len(text) >= 5 and any(c.islower() for c in text) and not self._is_label(seg):
                return clean_ocr_text(text)
        return None

    # ------------------------------------------------------------------ totaux
    def _amount_on_line(self, ln: Line, label_end: int | None = None) -> Decimal | None:
        """Montant le plus à droite de la ligne, hors taux de TVA."""
        for seg in reversed(ln.segments):
            text = re.sub(r"\d{1,2}(?:[.,]\d{1,2})?\s*%", " ", seg.text)
            found = [m.group(0) for m in AMOUNT_RE.finditer(text)]
            if found:
                return parse_amount(found[-1])
        return None

    def _totals(self, inv: Invoice, ex: Extraction) -> None:
        start = 0
        for pos, _seg, _m in self._find_label(L_HT):
            v = self._amount_on_line(self.lines[pos.line])
            if v is not None:
                inv.total_without_vat = money(v)
                ex.set("total_without_vat", self._conf(0.9), "rules:label")
                start = pos.line
                break
        breakdown = []
        for pos, seg, m in self._find_label(L_TVA_RATE, start=start):
            if "intracom" in fold(seg.text):
                continue
            rate = parse_rate(m.group(1) + "%")
            v = self._amount_on_line(self.lines[pos.line])
            if rate is not None and v is not None and v != rate:
                breakdown.append(
                    VatBreakdown(rate=rate, taxable_amount=Decimal(0), tax_amount=money(v))
                )
        if breakdown:
            inv.vat_breakdown = breakdown
            inv.total_vat = money(sum(b.tax_amount for b in breakdown))
            ex.set("total_vat", self._conf(0.9), "rules:label-rates")
        for pos, _seg, _m in self._find_label(L_TVA_TOTAL, start=start):
            v = self._amount_on_line(self.lines[pos.line])
            if v is not None:
                if inv.total_vat is None:
                    inv.total_vat = money(v)
                    ex.set("total_vat", self._conf(0.9), "rules:label")
                break
        for pos, _seg, _m in self._find_label(L_TTC, start=start):
            v = self._amount_on_line(self.lines[pos.line])
            if v is not None:
                inv.total_with_vat = money(v)
                ex.set("total_with_vat", self._conf(0.9), "rules:label")
                break
        for pos, _seg, _m in self._find_label(L_DUE_AMOUNT, start=start):
            v = self._amount_on_line(self.lines[pos.line])
            if v is not None:
                inv.amount_due = money(v)
                break
        if None in (inv.total_without_vat, inv.total_vat, inv.total_with_vat):
            self._total_rows(inv, ex)

    def _total_rows(self, inv: Invoice, ex: Extraction) -> None:
        """Totaux sans libellé HT/TTC : ligne « Total » d'un récapitulatif de TVA, dont les
        montants s'équilibrent (HT + TVA = TTC), ou « TOTAL » seul suivi d'un montant."""
        lone_total = None
        for ln in self.lines:
            head = fold(ln.segments[0].text).strip(" :.")
            if not re.fullmatch(r"total(?:\s*general)?", head):
                continue
            values = []
            for seg in ln.segments[1:]:
                text = re.sub(r"\d{1,2}(?:[.,]\d{1,2})?\s*%", " ", seg.text)
                values += [parse_amount(m.group(0)) for m in AMOUNT_RE.finditer(text)]
            values = [v for v in values if v is not None]
            for k in range(len(values) - 2):
                ht, tva, ttc = values[k : k + 3]
                if ttc > 0 and money(ht + tva) == money(ttc):
                    for field, value in (
                        ("total_without_vat", ht),
                        ("total_vat", tva),
                        ("total_with_vat", ttc),
                    ):
                        if getattr(inv, field) is None:
                            setattr(inv, field, money(value))
                            ex.set(field, self._conf(0.9), "rules:total-row")
                    return
            if len(values) == 1 and lone_total is None:
                lone_total = values[0]
        if inv.total_with_vat is None and lone_total:
            inv.total_with_vat = money(lone_total)
            ex.set("total_with_vat", self._conf(0.75), "rules:total-alone")

    # ------------------------------------------------------------------ paiement, mentions
    def _payment_and_mentions(self, inv: Invoice, ex: Extraction) -> None:
        text = self.doc.text
        ftext = fold(text)
        for m in re.finditer(r"IBAN", text, re.IGNORECASE):
            window = text[m.end() : m.end() + 60].upper()
            for cand in RX_IBAN.finditer(window):
                raw = cand.group(1)
                groups = raw.split()
                for k in range(len(groups), 1, -1):  # retire d'éventuels groupes parasites
                    if ids.is_valid_iban("".join(groups[:k])):
                        inv.iban = ids.normalize_iban("".join(groups[:k]))
                        break
                if inv.iban is None and ids.is_valid_iban(raw):
                    inv.iban = ids.normalize_iban(raw)
                if inv.iban:
                    ex.set("iban", self._conf(0.97), "rules:mod97")
                    break
            if inv.iban:
                break
        m = RX_BIC.search(text.upper())
        if m:
            inv.bic = m.group(1)

        m = re.search(r"cat[eé]gorie\s*d.?\s*op[eé]rations?\s*:?\s*([^\n|]+)", ftext)
        if m:
            cat = self.parse_category(m.group(1))
            if cat:
                inv.operation_category = cat
                ex.set("operation_category", self._conf(0.95), "rules:label")
        inv.vat_on_debits = bool(
            re.search(r"d.?\s*apres\s*les\s*debits|tva\s*sur\s*les\s*debits", ftext)
        )

        for ln in self.lines:
            t = fold(ln.text)
            if inv.late_penalty_note is None and re.search(r"penalites?|retard\s*de\s*paiement", t):
                inv.late_penalty_note = ln.text
            if inv.recovery_fee_note is None and re.search(
                r"indemnite\s*forfaitaire|frais\s*de\s*recouvrement", t
            ):
                inv.recovery_fee_note = ln.text
            if inv.discount_note is None and "escompte" in t:
                inv.discount_note = ln.text
            if inv.payment_terms is None and re.search(
                r"paiement\s*(a|par|sous|comptant)|virement|a\s*reception", t
            ):
                inv.payment_terms = (
                    re.split(r"\.?\s*IBAN", ln.text, flags=re.IGNORECASE)[0].strip(" .") or None
                )

    @staticmethod
    def parse_category(text: str) -> OperationCategory | None:
        t = fold(text)
        if re.search(r"mixte|biens\s*et\s*(de\s*)?services|\blbps\b", t):
            return OperationCategory.MIXED
        if re.search(r"livraisons?\s*de\s*biens|\blb\b|\bbiens\b", t):
            return OperationCategory.GOODS
        if re.search(r"prestations?\s*de\s*services|\bps\b|services", t):
            return OperationCategory.SERVICES
        return None

    # ------------------------------------------------------------------ cohérence
    def _reconcile(self, inv: Invoice, ex: Extraction) -> None:
        """Complète les champs manquants par l'arithmétique et ventile la TVA."""
        if inv.lines and inv.total_without_vat is None:
            inv.total_without_vat = money(sum(ln.net_amount or 0 for ln in inv.lines))
            ex.set("total_without_vat", self._conf(0.6), "rules:sum-lines")
        if inv.total_with_vat is None and inv.amount_due:  # un solde nul n'est pas un total
            inv.total_with_vat = inv.amount_due
            ex.set("total_with_vat", self._conf(0.7), "rules:from-due")
        if (
            inv.total_vat is None
            and inv.total_with_vat is not None
            and inv.total_without_vat is not None
        ):
            inv.total_vat = money(inv.total_with_vat - inv.total_without_vat)
            ex.set("total_vat", self._conf(0.6), "rules:difference")
        if inv.amount_due is None:
            inv.amount_due = inv.total_with_vat
        # un seul taux sur les lignes et des totaux cohérents avec lui : ventilation directe
        rates = {ln.vat_rate for ln in inv.lines if ln.vat_rate is not None}
        if (
            not inv.vat_breakdown
            and len(rates) == 1
            and None not in (inv.total_without_vat, inv.total_vat)
        ):
            rate = rates.pop()
            if abs(money(inv.total_without_vat * rate / 100) - inv.total_vat) <= Decimal("0.02"):
                inv.vat_breakdown = [
                    VatBreakdown(
                        rate=rate, taxable_amount=inv.total_without_vat, tax_amount=inv.total_vat
                    )
                ]
        # bases imposables par taux, à partir des lignes
        if inv.vat_breakdown:
            by_rate: dict[Decimal, Decimal] = {}
            for ln in inv.lines:
                if ln.vat_rate is not None and ln.net_amount is not None:
                    by_rate[ln.vat_rate] = by_rate.get(ln.vat_rate, Decimal(0)) + ln.net_amount
            single = len(inv.vat_breakdown) == 1
            for vb in inv.vat_breakdown:
                if vb.rate in by_rate:
                    vb.taxable_amount = money(by_rate[vb.rate])
                elif single and inv.total_without_vat is not None:
                    vb.taxable_amount = inv.total_without_vat
                else:
                    vb.taxable_amount = (
                        money(vb.tax_amount * 100 / vb.rate) if vb.rate else Decimal(0)
                    )
            if single:
                for ln in inv.lines:
                    if ln.vat_rate is None:
                        ln.vat_rate = inv.vat_breakdown[0].rate
        # cohérence globale : confirme ou affaiblit la confiance
        if None not in (inv.total_without_vat, inv.total_vat, inv.total_with_vat):
            ok = money(inv.total_without_vat + inv.total_vat) == money(inv.total_with_vat)
            for f in ("total_without_vat", "total_vat", "total_with_vat"):
                fc = ex.confidence.get(f)
                if fc:
                    ex.set(
                        f,
                        min(1.0, fc.value + 0.05) if ok else fc.value * 0.6,
                        fc.source + ("+balanced" if ok else "+unbalanced"),
                    )
