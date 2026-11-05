"""Refresh the public, tissue-level extract; never download donor records."""

import csv
import hashlib
import io
import json
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src/omics_rag/data"
GENES = [
    "ALB",
    "INS",
    "GCG",
    "SST",
    "TP53",
    "BRCA1",
    "BRCA2",
    "EGFR",
    "ERBB2",
    "VEGFA",
    "APOE",
    "GFAP",
    "MBP",
    "CD3D",
    "CD8A",
    "MS4A1",
    "ACTB",
    "GAPDH",
    "ACE2",
    "SLC2A1",
]
DESCRIPTIONS = {
    "hpa": "Human Protein Atlas RNA sequencing in normal human tissues. Gene-level normalized RNA abundance in nTPM; independent HPA tissue collection.",
    "gtex": "GTEx normal human tissue RNA sequencing, distributed by the Human Protein Atlas. Gene-level normalized RNA abundance in nTPM from a separate donor collection.",
    "consensus": "Human Protein Atlas consensus normal tissue RNA expression. Maximum normalized nTPM across HPA and GTEx, not an independent replication or an average.",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = []
    rows = []
    for source, description in DESCRIPTIONS.items():
        url = f"https://www.proteinatlas.org/download/tsv/rna_tissue_{source}.tsv.zip"
        with tempfile.TemporaryDirectory(prefix="omics-download-") as temp:
            archive = Path(temp) / "data.zip"
            subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--location",
                    "--http1.1",
                    "--max-time",
                    "120",
                    url,
                    "-o",
                    str(archive),
                ],
                check=True,
            )
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with zipfile.ZipFile(archive) as zipped:
                with zipped.open(f"rna_tissue_{source}.tsv") as handle:
                    for row in csv.DictReader(io.TextIOWrapper(handle), delimiter="\t"):
                        if row["Gene name"] in GENES:
                            rows.append(
                                {
                                    "source": source,
                                    "ensembl": row["Gene"],
                                    "gene": row["Gene name"],
                                    "tissue": row["Tissue"],
                                    "ntpm": row["nTPM"],
                                }
                            )
        sources.append(
            {
                "id": source,
                "title": f"HPA v25.1 {source} tissue RNA",
                "url": url,
                "description": description,
                "archive_sha256": digest,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "version": "25.1",
            }
        )
        print(source, sum(r["source"] == source for r in rows))
    rows.sort(key=lambda r: (r["source"], r["gene"], r["tissue"]))
    target = OUT / "expression.tsv"
    with target.open("w") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["source", "ensembl", "gene", "tissue", "ntpm"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "genes": GENES,
        "sources": sources,
        "extract_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "rows": len(rows),
        "licence": "https://www.proteinatlas.org/about/licence",
        "method": "Exact Gene name filter, all tissue rows; retain nTPM unchanged; no donor-level data.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
