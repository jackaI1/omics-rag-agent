"""Small, pinned sentence encoder; normal operation never downloads anything."""

import hashlib
import json
import os
from importlib.resources import files
from pathlib import Path
from urllib.request import urlopen

import numpy as np

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_FILE = "onnx/model_qint8_arm64.onnx"
DIMENSION = 384


def text_key(text):
    return hashlib.sha256(text.encode()).hexdigest()


def download_model(directory):
    """Explicit opt-in, bounded to 32 MB total, no full model snapshot or torch."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name in (MODEL_FILE, "tokenizer.json"):
        target = directory / Path(name).name
        partial = target.with_suffix(".part")
        try:
            with urlopen(f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}") as src:
                with partial.open("wb") as dest:
                    count = 0
                    while chunk := src.read(1024 * 1024):
                        count += len(chunk)
                        if count > 32_000_000:
                            raise ValueError("Unexpectedly large model file")
                        dest.write(chunk)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    if sum(p.stat().st_size for p in directory.iterdir() if p.is_file()) > 32_000_000:
        raise ValueError("Encoder directory exceeds 32 MB budget")


class LocalEncoder:
    """ONNX token embeddings -> masked mean pooling -> unit sentence vectors."""

    def __init__(self, directory):
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as error:
            raise RuntimeError("Install local inference with uv sync --extra embeddings") from error

        directory = Path(directory)
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(directory / Path(MODEL_FILE).name),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def encode(self, texts):
        output = []
        for start in range(0, len(texts), 32):
            tokens = self.tokenizer.encode_batch(texts[start : start + 32])
            inputs = {
                "input_ids": np.array([t.ids for t in tokens], dtype="int64"),
                "attention_mask": np.array([t.attention_mask for t in tokens], dtype="int64"),
                "token_type_ids": np.array([t.type_ids for t in tokens], dtype="int64"),
            }
            hidden = self.session.run(None, inputs)[0]
            mask = inputs["attention_mask"][..., None]
            pooled = (hidden * mask).sum(axis=1) / mask.sum(axis=1).clip(min=1)
            pooled /= np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-12)
            output.append(pooled.astype("float32"))
        return np.concatenate(output) if output else np.empty((0, DIMENSION), dtype="float32")


class CachedEncoder:
    """Frozen corpus/query cache; optional local inference for unseen queries."""

    def __init__(self, directory=None):
        data = files("omics_rag").joinpath("data")
        metadata = json.loads(data.joinpath("embedding-cache.json").read_text())
        raw = data.joinpath("embedding-cache.npz").read_bytes()
        if hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
            raise ValueError("Embedding cache checksum mismatch")
        if (metadata["model"], metadata["revision"], metadata["dimension"]) != (
            MODEL,
            REVISION,
            DIMENSION,
        ):
            raise ValueError("Embedding cache model mismatch; rebuild it")
        from io import BytesIO

        with np.load(BytesIO(raw), allow_pickle=False) as cache:
            vectors = cache["vectors"]
            keys = cache["keys"].tolist()
        if vectors.shape != (len(keys), DIMENSION) or not np.isfinite(vectors).all():
            raise ValueError("Invalid cached embedding vectors")
        if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5):
            raise ValueError("Cached embeddings must have unit length")
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate embedding cache keys")
        self.metadata = metadata
        self.cache = dict(zip(keys, vectors, strict=True))
        self.directory = directory or os.environ.get("OMICS_EMBEDDING_MODEL")
        self.local = None

    def encode(self, texts):
        missing = list(dict.fromkeys(t for t in texts if text_key(t) not in self.cache))
        if missing:
            if not self.directory:
                raise ValueError(
                    "Text absent from offline embedding cache. Set OMICS_EMBEDDING_MODEL "
                    "to a local encoder directory; see docs/retrieval.md. TF-IDF works without it."
                )
            if self.local is None:
                for filename, checksum in (
                    (Path(MODEL_FILE).name, self.metadata["model_file_sha256"]),
                    ("tokenizer.json", self.metadata["tokenizer_sha256"]),
                ):
                    if (
                        hashlib.sha256((Path(self.directory) / filename).read_bytes()).hexdigest()
                        != checksum
                    ):
                        raise ValueError(
                            "Local encoder differs from the cached model; rebuild cache"
                        )
                self.local = LocalEncoder(self.directory)
            self.cache.update(zip(map(text_key, missing), self.local.encode(missing), strict=True))
        return np.array([self.cache[text_key(t)] for t in texts], dtype="float32")
