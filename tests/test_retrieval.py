import json
import subprocess
import sys
from unittest.mock import patch

import faiss
import numpy as np
import pytest

from omics_rag.agents import QA
from omics_rag.embeddings import DIMENSION, CachedEncoder
from omics_rag.retrieval import MeasurementIndex, measurement_documents
from omics_rag.retrieval_evaluation import cases, evaluate, metrics
from omics_rag.store import Store


@pytest.fixture(scope="module")
def store():
    instance = Store()
    yield instance
    instance.close()


@pytest.fixture(scope="module")
def index(store):
    return MeasurementIndex(store)


def test_cached_vectors_are_real_normalized_and_match_entire_corpus(store):
    with patch("socket.socket", side_effect=AssertionError("Network forbidden")):
        encoder = CachedEncoder()
        vectors = encoder.encode([d["text"] for d in measurement_documents(store)])
    assert vectors.shape == (2540, DIMENSION)
    assert np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    assert not np.allclose(vectors[0], vectors[1])


def test_faiss_index_round_trip(index, tmp_path):
    dense = index._dense_index()
    assert isinstance(dense, faiss.IndexFlatIP)
    assert dense.ntotal == 2540 and dense.d == DIMENSION
    path = tmp_path / "measurements.faiss"
    faiss.write_index(dense, str(path))
    restored = faiss.read_index(str(path))
    query = index.encoder.encode([cases()[0]["query"]])
    before = dense.search(query, 5)
    after = restored.search(query, 5)
    assert np.array_equal(before[1], after[1])
    assert np.allclose(before[0], after[0])


@pytest.mark.parametrize("mode", ["tfidf", "embedding", "hybrid"])
def test_ranked_retrieval_keeps_gene_scope_and_citations(index, store, mode):
    query = "ALB expression in liver"
    with patch("socket.socket", side_effect=AssertionError("Network forbidden")):
        hits = index.search(query, ["ALB"], mode=mode, k=5)
    assert len(hits) == 5
    assert len({h["id"] for h in hits}) == 5
    assert all(h["gene"] == "ALB" and h["url"].startswith("https://") for h in hits)
    assert hits[0]["tissue"] == "liver"
    assert all(h["text"] in [d["text"] for d in index.documents] for h in hits)
    assert all(store.rows[h["id"]]["source"] == h["source"] for h in hits)


def test_semantic_paraphrase_finds_cardiac_measurements(index):
    hits = index.search("ACTB transcript levels in cardiac tissue", ["ACTB"], "embedding", 5)
    assert hits[0]["tissue"] == "heart muscle"


def test_hybrid_is_reciprocal_rank_fusion(index):
    query = cases()[0]["query"]
    lexical = index.search(query, ["ALB"], "tfidf", 100)
    dense = index.search(query, ["ALB"], "embedding", 100)
    hit = index.search(query, ["ALB"], "hybrid", 1)[0]
    lexical_rank = next(i for i, h in enumerate(lexical, 1) if h["id"] == hit["id"])
    dense_rank = next(i for i, h in enumerate(dense, 1) if h["id"] == hit["id"])
    assert hit["rank_score"] == pytest.approx(1 / (60 + lexical_rank) + 1 / (60 + dense_rank))


def test_no_gene_never_guesses_or_downloads(index):
    assert index.search("unseen text", [], "embedding") == []
    assert index.search("unseen text", ["FAKE"], "embedding") == []


def test_unseen_text_has_actionable_offline_error(monkeypatch):
    monkeypatch.delenv("OMICS_EMBEDDING_MODEL", raising=False)
    with patch("socket.socket", side_effect=AssertionError("Network forbidden")):
        with pytest.raises(ValueError, match="OMICS_EMBEDDING_MODEL"):
            CachedEncoder().encode(["this query was deliberately never cached"])


@pytest.mark.parametrize("mode,k", [("unknown", 5), ("tfidf", 0), ("hybrid", 101)])
def test_invalid_retrieval_settings(index, mode, k):
    with pytest.raises(ValueError):
        index.search("ALB", ["ALB"], mode, k)


def test_metrics_known_ranking_duplicates_and_cutoff():
    assert metrics([9, 3, 3, 5], [3, 5], 3) == {"recall@3": 1, "mrr@3": 0.5}
    assert metrics([9, 8, 3], [3, 5], 2) == {"recall@2": 0, "mrr@2": 0}
    assert metrics([], [3], 5) == {"recall@5": 0, "mrr@5": 0}
    assert metrics([3], [3, 5], 1) == {"recall@1": 0.5, "mrr@1": 1}
    with pytest.raises(ValueError):
        metrics([1], [], 5)
    with pytest.raises(ValueError):
        metrics([1], [1], 0)


def test_full_offline_evaluation_has_valid_labels(store, monkeypatch):
    monkeypatch.delenv("OMICS_EMBEDDING_MODEL", raising=False)
    with patch("socket.socket", side_effect=AssertionError("Network forbidden")):
        report = evaluate(store)
    assert report["queries"] == 24
    assert report["documents"] == 2540
    assert {r["mode"] for r in report["results"]} == {"tfidf", "embedding", "hybrid"}
    for result in report["results"]:
        assert 0 <= result["recall@5"] <= 1
        assert 0 <= result["mrr@5"] <= 1
        assert len(result["queries"]) == 24
        assert all(q["relevant_ids"] for q in result["queries"])


def test_dense_path_integrates_with_answer_agent():
    with QA(retrieval="embedding") as qa:
        result = qa.ask("ALB expression in liver", force_agents=True)
    assert len(result["rows"]) == 3
    assert len(result["retrieved_documents"]) == 6
    assert result["retrieved_documents"][0]["tissue"] == "liver"
    assert {r["source"] for r in result["rows"]} == {"hpa", "gtex", "consensus"}


def test_cli_dense_search_is_offline():
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "omics_rag.cli",
            "ACTB transcript levels in cardiac tissue",
            "--search",
            "--retrieval",
            "embedding",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(run.stdout)[0]["tissue"] == "heart muscle"


def test_corrupt_cache_fails_closed(tmp_path):
    from importlib.resources import files

    data = tmp_path / "data"
    data.mkdir()
    metadata = files("omics_rag").joinpath("data/embedding-cache.json").read_text()
    (data / "embedding-cache.json").write_text(metadata)
    (data / "embedding-cache.npz").write_bytes(b"modified cache")
    with patch("omics_rag.embeddings.files", return_value=tmp_path):
        with pytest.raises(ValueError, match="checksum"):
            CachedEncoder()
