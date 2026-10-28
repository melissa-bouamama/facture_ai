"""Assemblage du PDF Factur-X : le PDF d'origine + le XML CII embarqué + métadonnées XMP."""

from __future__ import annotations

import logging

import facturx

from ..models import Invoice

log = logging.getLogger(__name__)


def embed_facturx(pdf_bytes: bytes, xml_bytes: bytes, inv: Invoice) -> bytes:
    """Renvoie un PDF Factur-X (profil EN 16931) lisible par un humain et par une machine.

    Le XML est vérifié contre le XSD au passage. La conformité PDF/A-3 stricte dépend
    du PDF source (polices incorporées, profil ICC) : pour un dépôt en production,
    convertir d'abord la source en PDF/A (Ghostscript, veraPDF pour le contrôle).
    """
    metadata = {
        "author": inv.seller.name or "",
        "keywords": "Factur-X, EN 16931",
        "title": f"{inv.seller.name or ''}: Facture {inv.number}",
        "subject": f"Facture {inv.number} du {inv.issue_date} - {inv.buyer.name or ''}",
    }
    return facturx.generate_from_binary(
        pdf_bytes,
        xml_bytes,
        flavor="factur-x",
        level="en16931",
        check_xsd=True,
        pdf_metadata=metadata,
        lang="fr-FR",
    )


def read_facturx_xml(pdf_bytes: bytes) -> bytes | None:
    """Extrait le XML embarqué d'un PDF Factur-X (utile pour vérifier l'aller-retour)."""
    _, xml = facturx.get_xml_from_pdf(pdf_bytes, check_xsd=False)
    return xml or None
