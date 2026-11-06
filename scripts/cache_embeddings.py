"""Rebuild frozen vectors with real local inference, without an embedding service."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from omics_rag.embeddings import (
    DIMENSION,
    MODEL,
    MODEL_FILE,
    REVISION,
    LocalEncoder,
    download_model,
    text_key,
)
from omics_rag.retrieval import measurement_documents
from omics_rag.retrieval_evaluation import cases
from omics_rag.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--download", action="store_true", help="Download only the 23 MB encoder")
    args = parser.parse_args()
    if args.download:
        download_model(args.model_dir)
    store = Store()
    try:
        texts = list(
            dict.fromkeys(
                [d["text"] for d in measurement_documents(store)] + [c["query"] for c in cases()]
            )
        )
        encoder = LocalEncoder(args.model_dir)
        vectors = encoder.encode(texts)
        output = Path(__file__).resolve().parents[1] / "src/omics_rag/data"
        target = output / "embedding-cache.npz"
        np.savez_compressed(target, keys=np.array([text_key(t) for t in texts]), vectors=vectors)
        metadata = {
            "model": MODEL,
            "revision": REVISION,
            "model_file": MODEL_FILE,
            "model_file_sha256": hashlib.sha256(
                (args.model_dir / Path(MODEL_FILE).name).read_bytes()
            ).hexdigest(),
            "tokenizer_sha256": hashlib.sha256(
                (args.model_dir / "tokenizer.json").read_bytes()
            ).hexdigest(),
            "dimension": DIMENSION,
            "pooling": "attention-mask mean, L2 normalization, max_length=256",
            "rows": len(texts),
            "extract_sha256": store.manifest["extract_sha256"],
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        (output / "embedding-cache.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"Cached {len(texts)} real sentence embeddings; {target.stat().st_size} bytes")
    finally:
        store.close()


if __name__ == "__main__":
    main()
