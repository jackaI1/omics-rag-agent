"""Human-labelled measurement targets; metrics independent of answer generation."""

import json
from importlib.resources import files

from .retrieval import MODES, MeasurementIndex


def cases():
    return json.loads(files("omics_rag").joinpath("data/retrieval-queries.json").read_text())


def metrics(ranked_ids, relevant_ids, k):
    if type(k) is not int or k < 1 or not relevant_ids:
        raise ValueError("Metrics need a positive k and nonempty relevance labels")
    relevant = set(relevant_ids)
    # Deduplicate before truncation; repeated hits never inflate recall or consume ranks.
    ranked = list(dict.fromkeys(ranked_ids))[:k]
    recall = len(set(ranked) & relevant) / len(relevant)
    reciprocal = next((1 / rank for rank, item in enumerate(ranked, 1) if item in relevant), 0)
    return {f"recall@{k}": recall, f"mrr@{k}": reciprocal}


def evaluate(store, k=5):
    index = MeasurementIndex(store)
    results = []
    labels = cases()
    for mode in MODES:
        per_query = []
        for case in labels:
            target = case["relevant"]
            relevant = [
                row["id"]
                for row in store.rows.values()
                if all(row[key] == value for key, value in target.items())
            ]
            if not relevant:
                raise ValueError(f"No relevant rows for {case['id']}")
            genes, _ = store.entities(case["query"])
            hits = index.search(case["query"], genes, mode, k)
            per_query.append(
                {
                    "id": case["id"],
                    "ranked_ids": [h["id"] for h in hits],
                    "relevant_ids": relevant,
                    **metrics([h["id"] for h in hits], relevant, k),
                }
            )
        results.append(
            {
                "mode": mode,
                **{
                    metric: sum(r[metric] for r in per_query) / len(per_query)
                    for metric in (f"recall@{k}", f"mrr@{k}")
                },
                "queries": per_query,
            }
        )
    return {"queries": len(labels), "documents": len(index.documents), "k": k, "results": results}
