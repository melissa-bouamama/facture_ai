"""Validation du XML : XSD (toujours) et schematrons EN 16931 / BR-FR (si Saxon est installé).

Les schematrons officiels sont compilés en XSLT 2.0, que lxml ne sait pas exécuter.
On utilise SaxonC-HE (`pip install saxonche`) directement en Python, sans serveur.
Les fichiers XSD et XSLT sont ceux distribués avec la bibliothèque `factur-x`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import facturx
from lxml import etree

SVRL = "{http://purl.oclc.org/dsdl/svrl}"
_BASE = os.path.join(os.path.dirname(facturx.__file__), "xsd_and_schematron")
SCHEMATRONS = {
    "en16931": os.path.join(_BASE, "facturx-en16931", "FACTUR-X_EN16931.xslt"),
    "br-fr": os.path.join(_BASE, "cii-schematron-fr-ctc", "BR-FR-Flux2-Schematron-CII.xslt"),
}


@dataclass
class XmlReport:
    xsd_valid: bool
    xsd_error: str | None = None
    schematron_run: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.xsd_valid and not any(f["flag"] in ("fatal", "error") for f in self.failures)


def check_xsd(xml: bytes) -> tuple[bool, str | None]:
    try:
        facturx.xml_check_xsd(xml, flavor="factur-x", level="en16931")
        return True, None
    except Exception as exc:  # la lib lève une Exception générique avec le détail
        return False, str(exc)


def saxon_available() -> bool:
    try:
        import saxonche  # noqa: F401
    except ImportError:
        return False
    return True


def run_schematrons(
    xml: bytes, which: tuple[str, ...] = ("en16931", "br-fr")
) -> tuple[list[str], list[dict]]:
    from saxonche import PySaxonProcessor

    failures: list[dict] = []
    ran: list[str] = []
    with PySaxonProcessor(license=False) as proc:
        xslt = proc.new_xslt30_processor()
        doc = proc.parse_xml(xml_text=xml.decode("utf-8"))
        for name in which:
            executable = xslt.compile_stylesheet(stylesheet_file=SCHEMATRONS[name])
            svrl = executable.transform_to_string(xdm_node=doc)
            ran.append(name)
            tree = etree.fromstring(svrl.encode("utf-8"))
            for fa in tree.iter(f"{SVRL}failed-assert", f"{SVRL}successful-report"):
                text = fa.find(f"{SVRL}text")
                failures.append(
                    {
                        "schematron": name,
                        "id": fa.get("id"),
                        "flag": fa.get("flag") or "error",
                        "location": fa.get("location"),
                        "message": " ".join((text.text or "").split()) if text is not None else "",
                    }
                )
    return ran, failures


def check_xml(xml: bytes, schematron: bool = True) -> XmlReport:
    ok, err = check_xsd(xml)
    report = XmlReport(xsd_valid=ok, xsd_error=err)
    if schematron and saxon_available():
        report.schematron_run, report.failures = run_schematrons(xml)
    return report
