"""Extracteurs disponibles : `rules` (déterministe), `llm` (LLM local ou API), `hybrid`."""

from __future__ import annotations

from .base import CORE_FIELDS, TRACKED_FIELDS, Extraction, Extractor
from .rules import RulesExtractor

__all__ = [
    "CORE_FIELDS",
    "TRACKED_FIELDS",
    "Extraction",
    "Extractor",
    "RulesExtractor",
    "get_extractor",
]


def get_extractor(name: str = "rules") -> Extractor:
    if name == "rules":
        return RulesExtractor()
    if name == "llm":
        from .llm import LLMExtractor

        return LLMExtractor()
    if name == "hybrid":
        from .hybrid import HybridExtractor

        return HybridExtractor()
    raise ValueError(f"Extracteur inconnu : {name} (attendu : rules, llm, hybrid)")
