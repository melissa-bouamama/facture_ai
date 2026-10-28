"""Lecture d'un PDF en mots positionnés, puis reconstruction de la mise en page.

Deux chemins d'entrée :
- PDF natif : les mots et leurs coordonnées sont lus directement (pdfplumber) ;
- PDF scanné : la page est rastérisée puis passée à Tesseract (fra+eng), qui renvoie
  aussi des boîtes englobantes et une confiance par mot.

Dans les deux cas on obtient la même structure (`Document` → `Page` → `Line` →
`Segment`), ce qui permet au reste du pipeline d'ignorer l'origine du texte.
Le découpage des lignes en segments évite l'écueil classique des factures sur deux
colonnes (vendeur à gauche, client à droite) dont les textes seraient fusionnés par
une simple extraction ligne à ligne.
"""

from __future__ import annotations

import io
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

log = logging.getLogger(__name__)

MIN_NATIVE_CHARS = 40  # en dessous, la page est considérée comme scannée
OCR_DPI = 300


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    conf: float = 1.0

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass
class Segment:
    """Suite de mots contigus sur une même ligne visuelle (une « cellule »)."""

    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return self.words[0].x0

    @property
    def x1(self) -> float:
        return self.words[-1].x1

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def conf(self) -> float:
        return min(w.conf for w in self.words)


@dataclass
class Line:
    segments: list[Segment]

    @property
    def top(self) -> float:
        return min(s.top for s in self.segments)

    @property
    def bottom(self) -> float:
        return max(s.bottom for s in self.segments)

    @property
    def text(self) -> str:
        return " | ".join(s.text for s in self.segments)


@dataclass
class Page:
    number: int
    width: float
    height: float
    words: list[Word]
    lines: list[Line] = field(default_factory=list)


@dataclass
class Document:
    pages: list[Page]
    source: str  # "native" | "ocr" | "mixed"
    path: str | None = None

    @property
    def lines(self) -> list[Line]:
        return [ln for p in self.pages for ln in p.lines]

    @property
    def text(self) -> str:
        """Texte ligne à ligne ; les cellules d'une même ligne sont séparées par « | »."""
        return "\n".join(ln.text for ln in self.lines)

    @property
    def mean_conf(self) -> float:
        confs = [w.conf for p in self.pages for w in p.words]
        return sum(confs) / len(confs) if confs else 0.0


def build_lines(words: list[Word]) -> list[Line]:
    """Regroupe les mots en lignes, puis découpe chaque ligne en segments."""
    if not words:
        return []
    med_h = statistics.median(w.height for w in words) or 8.0
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (round(w.top, 1), w.x0)):
        center = (w.top + w.bottom) / 2
        if rows:
            last = rows[-1]
            last_center = statistics.mean((x.top + x.bottom) / 2 for x in last)
            if abs(center - last_center) <= 0.45 * med_h:
                last.append(w)
                continue
        rows.append([w])

    gap_threshold = 1.2 * med_h
    lines = []
    for row in rows:
        row.sort(key=lambda w: w.x0)
        segments: list[Segment] = [Segment([row[0]])]
        for w in row[1:]:
            if w.x0 - segments[-1].x1 > gap_threshold:
                segments.append(Segment([w]))
            else:
                segments[-1].words.append(w)
        lines.append(Line(segments))
    return lines


def _native_words(page: pdfplumber.page.Page) -> list[Word]:
    raw = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5)
    return [Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"]) for w in raw]


def estimate_skew(image, max_angle: float = 3.0, step: float = 0.1) -> float:
    """Estime l'inclinaison d'un scan par profil de projection horizontal.

    Pour chaque angle candidat, on fait pivoter une version réduite de l'image et on
    mesure la netteté du profil des lignes (variance de sa dérivée) : les lignes de texte
    sont les plus nettes quand la page est droite. Un écart de 1° suffit à mélanger deux
    lignes d'un tableau sur la largeur d'une page A4, d'où cette étape avant l'OCR.
    """
    import numpy as np
    from PIL import Image

    small = image.copy()
    small.thumbnail((1000, 1000))
    inverted = Image.fromarray(255 - np.asarray(small, dtype=np.uint8))
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + 1e-9, step):
        rotated = np.asarray(
            inverted.rotate(float(angle), resample=Image.BILINEAR), dtype=np.float32
        )
        score = float(np.var(np.diff(rotated.sum(axis=1))))
        if score > best_score:
            best_angle, best_score = float(angle), score
    return round(best_angle, 2)


def _ocr_words(page: pdfplumber.page.Page, lang: str = "fra+eng") -> list[Word]:
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - dépend de l'installation
        raise RuntimeError(
            "PDF scanné détecté : installez l'extra OCR (pip install 'factur-ia[ocr]') "
            "et le binaire tesseract avec la langue 'fra'."
        ) from exc

    from PIL import Image

    image = page.to_image(resolution=OCR_DPI).original.convert("L")
    angle = estimate_skew(image)
    if abs(angle) >= 0.1:
        log.info("redressement de %.1f°", angle)
        image = image.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    data = pytesseract.image_to_data(
        image, lang=lang, config="--psm 3", output_type=pytesseract.Output.DICT
    )
    scale = 72.0 / OCR_DPI
    words = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:
            continue
        x, y, w, h = (data[k][i] * scale for k in ("left", "top", "width", "height"))
        words.append(Word(text, x, x + w, y, y + h, conf=conf / 100.0))
    return words


def read_pdf(
    source: str | Path | bytes, force_ocr: bool = False, ocr_lang: str = "fra+eng"
) -> Document:
    """Lit un PDF (chemin ou octets) et renvoie un `Document` structuré."""
    stream = io.BytesIO(source) if isinstance(source, bytes) else source
    pages: list[Page] = []
    kinds: set[str] = set()
    with pdfplumber.open(stream) as pdf:
        for i, p in enumerate(pdf.pages, start=1):
            words = [] if force_ocr else _native_words(p)
            if force_ocr or sum(len(w.text) for w in words) < MIN_NATIVE_CHARS:
                log.info("page %d : texte natif insuffisant, passage en OCR", i)
                words = _ocr_words(p, lang=ocr_lang)
                kinds.add("ocr")
            else:
                kinds.add("native")
            page = Page(number=i, width=float(p.width), height=float(p.height), words=words)
            page.lines = build_lines(words)
            pages.append(page)
    source_kind = kinds.pop() if len(kinds) == 1 else "mixed"
    return Document(
        pages=pages, source=source_kind, path=None if isinstance(source, bytes) else str(source)
    )
