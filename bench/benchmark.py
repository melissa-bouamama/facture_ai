"""Benchmark reproductible : génère les deux jeux de test puis évalue un extracteur.

    python bench/run_benchmark.py                      # extracteur à règles
    python bench/run_benchmark.py --backend hybrid     # nécessite un LLM (FACTURIA_LLM_BASE_URL)

Jeux générés (graines fixes) :
- `in-distribution` : 200 factures, 4 gabarits, 30 % dégradées en scan ;
- `hors-gabarit`    : 60 factures sur un gabarit dont le vocabulaire n'a pas servi à écrire
                      les règles — mesure la généralisation et les erreurs silencieuses.
"""

from __future__ import annotations

import argparse
import json
import platform
from datetime import date
from pathlib import Path

from facturia.evaluate import evaluate
from facturia.synth import HELDOUT_TEMPLATES, generate_dataset

ROOT = Path(__file__).parent
DATASETS = {
    "in-distribution": {"n": 200, "seed": 2026, "templates": None},
    "hors-gabarit": {"n": 60, "seed": 99, "templates": HELDOUT_TEMPLATES},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="rules", choices=["rules", "llm", "hybrid"])
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    summary = {"backend": args.backend, "date": date.today().isoformat(), "python": platform.python_version(),
               "cpu": platform.processor() or platform.machine(), "datasets": {}}  # fmt: skip
    for name, cfg in DATASETS.items():
        folder = args.data / name
        if not any(folder.glob("*.pdf")):
            generate_dataset(
                folder, n=cfg["n"], seed=cfg["seed"], scanned_ratio=0.3, templates=cfg["templates"]
            )
        result = evaluate(folder, extractor=args.backend)
        md = result.to_markdown(f"{name} — extracteur `{args.backend}`")
        (args.out / f"{args.backend}_{name}.md").write_text(md, encoding="utf-8")
        summary["datasets"][name] = {
            "n_docs": result.n_docs,
            "doc_exact": round(result.doc_exact, 4),
            "field_accuracy": {k: round(v, 4) for k, v in result.field_accuracy.items()},
            "decisions": result.decisions,
            "silent_errors": result.silent_errors,
            "reviewed_with_errors": result.reviewed_with_errors,
            "compliance": {
                k: {m: round(x, 4) for m, x in v.items()} for k, v in result.compliance.items()
            },
            "latency_ms": {
                k: {m: round(x, 1) for m, x in v.items()} for k, v in result.latency_ms.items()
            },
        }
        print(md)
    (args.out / f"{args.backend}_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
