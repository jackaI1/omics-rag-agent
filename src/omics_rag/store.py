"""Local expression database and a reproducible lexical vector index."""

import csv
import hashlib
import json
import re
import sqlite3
from importlib.resources import files
from threading import Lock

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from sklearn.feature_extraction.text import TfidfVectorizer


class TfidfEmbeddings(Embeddings):
    """Offline word vectors; lexical similarity, not a semantic neural encoder."""

    def __init__(self, texts):
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit(texts)

    def embed_documents(self, texts):
        return self.vectorizer.transform(texts).toarray().tolist()

    def embed_query(self, text):
        return self.embed_documents([text])[0]


class Store:
    def __init__(self, retrieval="tfidf"):
        self.retrieval = retrieval
        self.measurements = None
        data = files("omics_rag").joinpath("data")
        self.manifest = json.loads(data.joinpath("manifest.json").read_text())
        raw = data.joinpath("expression.tsv").read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.manifest["extract_sha256"]:
            raise ValueError("Expression extract checksum mismatch")
        self.sources = {s["id"]: s for s in self.manifest["sources"]}
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.query_lock = Lock()
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE expression (id INTEGER PRIMARY KEY, source TEXT, ensembl TEXT, gene TEXT, tissue TEXT, ntpm REAL)"
        )
        rows = list(csv.DictReader(raw.decode().splitlines(), delimiter="\t"))
        self.db.executemany(
            "INSERT INTO expression(source, ensembl, gene, tissue, ntpm) VALUES (:source,:ensembl,:gene,:tissue,:ntpm)",
            rows,
        )
        self.db.commit()
        self.genes = sorted({r["gene"] for r in rows})
        self.tissues = sorted({r["tissue"] for r in rows})
        self.rows = {r["id"]: dict(r) for r in self.db.execute("SELECT * FROM expression")}
        docs = []
        for source in self.sources.values():
            for gene in self.genes:
                tissues = sorted(
                    {r["tissue"] for r in rows if r["gene"] == gene and r["source"] == source["id"]}
                )
                docs.append(
                    Document(
                        page_content=f"{gene} expression. {source['description']} Tissues: {', '.join(tissues)}",
                        metadata={"gene": gene, "source": source["id"], "url": source["url"]},
                    )
                )
        self.vectors = InMemoryVectorStore(TfidfEmbeddings([d.page_content for d in docs]))
        self.vectors.add_documents(docs)

    def close(self):
        self.db.close()

    def entities(self, question):
        genes = [
            g
            for g in self.genes
            if re.search(r"(?<!\w)" + re.escape(g) + r"(?!\w)", question, re.IGNORECASE)
        ]
        # Longest names first prevents "muscle" from standing in for a specific tissue.
        tissues = [
            t
            for t in self.tissues
            if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", question, re.IGNORECASE)
        ]
        return genes, tissues

    def retrieve(self, query, genes):
        if not genes or any(g not in self.genes for g in genes):
            return {
                "documents": [],
                "ids": [],
                "missing": "Gene absent or not specified in this 20-gene extract.",
            }
        if self.retrieval != "tfidf":
            hits = self.search_measurements(query, genes, self.retrieval, k=6)
            return {
                "documents": hits,
                "ids": [i for i, r in self.rows.items() if r["gene"] in genes],
                "tissues": self.tissues,
                "genes": genes,
            }
        hits = self.vectors.similarity_search(
            query, k=6, filter=lambda d: d.metadata["gene"] in genes
        )
        return {
            "documents": [{"text": d.page_content, **d.metadata} for d in hits],
            "ids": [i for i, r in self.rows.items() if r["gene"] in genes],
            "tissues": self.tissues,
            "genes": genes,
        }

    def search_measurements(self, query, genes=None, mode="hybrid", k=5):
        from .retrieval import MeasurementIndex

        if self.measurements is None:
            self.measurements = MeasurementIndex(self)
        if genes is None:
            genes, _ = self.entities(query)
        return self.measurements.search(query, genes, mode, k)

    def query(self, sql, allowed_ids):
        with self.query_lock:
            return self._query(sql, allowed_ids)

    def _query(self, sql, allowed_ids):
        """Execute bounded read-only generated SQL; only row IDs may leave SQL."""
        if len(sql) > 4000 or not sql.lstrip().lower().startswith("select"):
            raise ValueError("Only SELECT queries of at most 4000 characters are allowed")
        allowed_actions = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ}

        def authorize(action, arg1, arg2, database, trigger):
            if action not in allowed_actions:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ and arg1 != "expression":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.db.set_authorizer(authorize)
        self.db.set_progress_handler(lambda: 1, 100_000)
        try:
            result = self.db.execute(sql)
            if [c[0] for c in result.description] != ["id"]:
                raise ValueError(
                    "SQL must return only id; measurements are loaded from trusted rows"
                )
            ids = [r[0] for r in result.fetchmany(101)]
            if len(ids) > 100 or any(type(i) is not int or i not in allowed_ids for i in ids):
                raise ValueError(
                    "Query exceeds 100 rows or returned evidence outside retrieval scope"
                )
            return [self.rows[i] for i in dict.fromkeys(ids)]
        except sqlite3.Error as error:
            raise ValueError(f"Rejected SQL: {error}") from error
        finally:
            self.db.set_authorizer(None)
            self.db.set_progress_handler(None, 0)
