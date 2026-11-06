"""Measurement-level lexical, dense and reciprocal-rank-fused retrieval."""

import faiss
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .embeddings import CachedEncoder

MODES = ("tfidf", "embedding", "hybrid")


def measurement_documents(store):
    return [
        {
            "id": row["id"],
            "gene": row["gene"],
            "tissue": row["tissue"],
            "source": row["source"],
            "url": store.sources[row["source"]]["url"],
            "text": (
                f"{row['gene']} RNA expression in {row['tissue']}. "
                f"{store.sources[row['source']]['description']} "
                f"Measured abundance: {row['ntpm']:g} nTPM."
            ),
        }
        for row in store.rows.values()
    ]


class MeasurementIndex:
    def __init__(self, store, encoder=None):
        self.documents = measurement_documents(store)
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
        self.lexical = self.vectorizer.fit_transform([d["text"] for d in self.documents])
        self.encoder = encoder
        self.dense = None

    def _dense_index(self):
        if self.dense is None:
            self.encoder = self.encoder or CachedEncoder()
            vectors = self.encoder.encode([d["text"] for d in self.documents])
            self.dense = faiss.IndexFlatIP(vectors.shape[1])
            self.dense.add(np.ascontiguousarray(vectors, dtype="float32"))
        return self.dense

    def search(self, query, genes, mode="hybrid", k=5):
        if mode not in MODES or type(k) is not int or not 1 <= k <= 100:
            raise ValueError("Choose tfidf/embedding/hybrid and k between 1 and 100")
        if not query.strip():
            raise ValueError("Query must not be empty")
        # Gene names are exact identifiers, not concepts to approximate with a language model.
        candidates = [i for i, d in enumerate(self.documents) if d["gene"] in genes]
        if not candidates:
            return []
        rankings = []
        if mode in ("tfidf", "hybrid"):
            scores = (self.lexical @ self.vectorizer.transform([query]).T).toarray().ravel()
            rankings.append(sorted(candidates, key=lambda i: (-float(scores[i]), i)))
        if mode in ("embedding", "hybrid"):
            index = self._dense_index()
            vector = self.encoder.encode([query])
            # Search all rows before metadata filtering: unrelated genes cannot crowd out hits.
            distances, positions = index.search(vector, index.ntotal)
            dense_scores = dict(zip(positions[0].tolist(), distances[0].tolist(), strict=True))
            rankings.append(sorted(candidates, key=lambda i: (-dense_scores[i], i)))
        # Full filtered lists, fixed RRF constant; no tuning against the labelled query set.
        rank_maps = [{item: position for position, item in enumerate(rank, 1)} for rank in rankings]
        fused = {i: sum(1 / (60 + ranks[i]) for ranks in rank_maps) for i in candidates}
        order = sorted(candidates, key=lambda i: (-fused[i], i))
        return [{**self.documents[i], "rank_score": fused[i]} for i in order[:k]]
