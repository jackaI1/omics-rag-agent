import pytest

from omics_rag.store import Store


@pytest.fixture(scope="module")
def store():
    instance = Store()
    yield instance
    instance.close()


def test_extract_integrity_and_known_value(store):
    assert len(store.rows) == store.manifest["rows"] == 2540
    assert len(store.genes) == 20
    row = next(
        r
        for r in store.rows.values()
        if r["gene"] == "ALB" and r["tissue"] == "liver" and r["source"] == "gtex"
    )
    assert row["ntpm"] == 60543.2
    assert all(s["archive_sha256"] and s["retrieved_at"] for s in store.sources.values())


def test_vector_retrieval_uses_gene_filter_and_source_text(store):
    result = store.retrieve("GTEx separate donor collection ALB", ["ALB"])
    assert result["documents"][0]["source"] == "gtex"
    assert {d["source"] for d in result["documents"]} == {"hpa", "gtex", "consensus"}
    assert all(store.rows[i]["gene"] == "ALB" for i in result["ids"])


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM expression",
        "SELECT id FROM expression; DROP TABLE expression",
        "SELECT id FROM sqlite_master",
        "SELECT load_extension('anything') AS id",
        "SELECT ntpm FROM expression LIMIT 1",
        "SELECT id FROM expression",
        "SELECT 999999 AS id",
        "SELECT 1.5 AS id",
        "PRAGMA table_info(expression)",
        "SELECT id FROM expression " + " " * 4000,
    ],
)
def test_reject_unsafe_or_unbounded_generated_code(store, sql):
    with pytest.raises(ValueError):
        store.query(sql, set(store.rows))
    # A rejected query cannot damage the next question.
    assert store.query("SELECT id FROM expression WHERE id=1", {1})[0]["id"] == 1


def test_cannot_cross_retrieved_gene_scope(store):
    with pytest.raises(ValueError, match="scope"):
        store.query("SELECT id FROM expression WHERE id=2", {1})


def test_vm_budget_interrupts_expensive_queries(store):
    with pytest.raises(ValueError, match="interrupted"):
        store.query(
            "SELECT a.id FROM expression a, expression b, expression c WHERE a.ntpm+b.ntpm+c.ntpm < -1",
            set(store.rows),
        )


def test_entity_boundaries(store):
    assert store.entities("INSIDE the liver")[0] == []
    assert store.entities("ins in pancreas") == (["INS"], ["pancreas"])
