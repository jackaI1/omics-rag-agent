# How I compare word matching with meaning

I kept the original source-description TF-IDF index for the default answer path. I added measurement-level search so I can find tissue rows using different wording, then inspect their values and sources. `--search` prints ranked measurement descriptions; `--retrieval embedding` or `hybrid` also selects that context for the existing retrieval agent. The structured gene scope and SQL safety checks remain the same.

## New questions and rebuilding the cache

The bundled cache contains real local model outputs for 2,540 measurement descriptions and the 24 labelled queries. It is about 3.8 MB. No model weights are committed. The fixed example questions work without inference dependencies or network access.

For arbitrary new wording, I install the optional CPU encoder and download just two pinned files, about 23 MB total:

```sh
uv sync --locked --dev --extra embeddings
uv run python scripts/cache_embeddings.py --model-dir .models/minilm --download
OMICS_EMBEDDING_MODEL=.models/minilm uv run --extra embeddings omics-rag \
  'ALB RNA in hepatic tissue' --search --retrieval embedding
```

`--download` is the only step that fetches model files. If they already exist, I omit it. The program never downloads in response to a question. Without a local encoder, an uncached query raises an error explaining the setup; TF-IDF remains available. New query vectors stay in process memory only. I delete `.models` when I no longer need the encoder. This uses CPU inference, without PyTorch, a model server, containers, or an API key.

After changing the extract, descriptions, labels, or encoder, I rebuild the cache and rerun:

```sh
uv run omics-rag --evaluate-retrieval > docs/retrieval-results.json
uv run pytest -q
```

I inspect the new results before updating the README. The cache metadata records the model revision, model and tokenizer checksums, input extract checksum, pooling method, dimension, and cache checksum. Cache lookup uses the SHA-256 of the exact text. Changed descriptions cannot silently reuse old vectors. Runtime inference also checks the local files against the cached encoder checksums.

## Encoder and index

I use the Apache-2.0 [all-MiniLM-L6-v2 sentence model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. The ONNX file is `onnx/model_qint8_arm64.onnx`; its integer-quantized weights are smaller than the full model. ONNX Runtime runs it locally. I tokenize up to 256 tokens, take the attention-mask-weighted mean of token vectors, and normalize the result to unit length, following the model's [mean-pooling recipe](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2#usage-huggingface-transformers).

Each indexed document describes one original row: gene symbol, tissue, source methods, measurement, and unit. Its metadata preserves the SQLite row ID and original download URL. TF-IDF and embedding search see identical text and exact gene filters. I require explicit gene symbols because the generic sentence model is not a reliable gene-identifier resolver.

`MeasurementIndex` stores the vectors in a local `faiss.IndexFlatIP`. Inner product on unit vectors is cosine similarity, a comparison of vector directions. FAISS stores all 2,540 vectors and searches them exactly; I filter by genes after searching the full index so unrelated genes cannot crowd out allowed candidates. Tests write and reload the FAISS index and compare results. The portable NPZ embedding cache rebuilds that small in-memory index on demand. SQLite remains authoritative for values and scope.

Hybrid adds `1 / (60 + rank)` from the full, gene-filtered lexical and dense lists, then sorts by that sum. This is reciprocal rank fusion with a fixed constant of 60 and equal weights. I did not tune it on the labelled questions. `rank_score` is this position-based score, including for a single-method result; it is not a probability or raw cosine score. Equal scores use original row order as the tie-breaker.

## Labels and measured results

[`retrieval-queries.json`](../src/omics_rag/data/retrieval-queries.json) has eight literal gene/tissue questions, eight tissue paraphrases, and eight questions selecting a source by name or method. I wrote the targets as explicit gene/tissue/source fields before measuring the rankings. A tissue-only target marks every available collection row for that tissue as relevant. A source-specific target marks just that source. One initially invalid HPA cerebellum target was corrected to an available liver row; there are no empty target sets.

[`retrieval-results.json`](retrieval-results.json) records every retrieved row ID and relevant row ID. At k=5, the macro averages over the 24 queries are:

| Method | Recall@5 | MRR@5 |
| --- | ---: | ---: |
| TF-IDF | 0.694444 | 0.631944 |
| Embedding | 0.972222 | 0.899306 |
| Hybrid | 0.763889 | 0.725694 |

Recall is unique relevant hits divided by the total number of relevant rows. Reciprocal rank is 1 divided by the first relevant position within five, or zero if none appears. MRR is the average reciprocal rank, truncated at k=5 here. I deduplicate hit IDs before truncation. These metrics evaluate retrieval, separately from the original 30 answer checks.

The dense model misses two of the three relevant esophagus rows for “food pipe” within five results. Equal-weight hybrid often brings lexical distractors back above semantic matches. The corpus and query set are small and manually selected, with no held-out training/tuning split, confidence intervals, or external benchmark. The model is general English, not a biomedical encoder. These are reproducible regression results on this extract, not a claim about all gene-expression questions. Exact gene filters are shared by every method and materially simplify the task. Dense context does not expand the deterministic mock's question grammar or automatically translate tissue synonyms into SQL filters.
