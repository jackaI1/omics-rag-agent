# Omics RAG Agent

I built a question-answering tool for public gene expression data because I wanted to compare where a gene is active without losing track of which table a number came from.

I ask about a gene and a tissue, and it shows the published RNA measurements with links to the original downloads. It can compare tissues, find the tissues with the highest measurements, and flag differences between two collections. Missing evidence stays missing instead of turning into a made-up answer.

Try it locally with [uv](https://docs.astral.sh/uv/getting-started/installation/), a Python package runner:

```sh
git clone https://github.com/jackaI1/omics-rag-agent.git
cd omics-rag-agent
uv sync --locked
uv run omics-rag 'ALB in liver'
uv run omics-rag 'Compare ALB in liver and pancreas'
uv run omics-rag 'Rank the top 3 tissues for INS'
```

These commands work offline after installation and need no account. They use a clearly labelled, rule-based mock model to make the examples repeatable. I can switch to a real local language model using the instructions below.

## Finding measurements by meaning

I can search descriptions of individual measurements when I do not know the table's exact wording. For example, “cardiac tissue” can find rows labelled “heart muscle”. The result includes the gene, tissue, collection, row number, and source link so I can check it.

```sh
uv run omics-rag 'ACTB transcript levels in cardiac tissue' --search --retrieval embedding
uv run omics-rag 'ALB expression in liver' --search --retrieval tfidf
uv run omics-rag 'ALB expression in liver' --search --retrieval hybrid
uv run omics-rag --evaluate-retrieval
```

These examples use cached sentence embeddings, which are numerical descriptions of meaning made by a small, open-source model running locally. They work offline after installation. The cache covers all bundled measurements and the 24 evaluation questions. For new wording I install the local encoder using [these steps](docs/retrieval.md#new-questions-and-rebuilding-the-cache); the program never downloads weights automatically. TF-IDF, the word-matching search, works for any wording without an encoder. Hybrid combines both rankings. I still require a gene symbol from the catalog.

I compared the same 2,540 measurement descriptions and exact gene filters on 24 manually labelled questions:

| Search | Recall@5 | MRR@5 |
| --- | ---: | ---: |
| TF-IDF, matching words | 0.694 | 0.632 |
| Embedding, matching meaning | 0.972 | 0.899 |
| Hybrid, combining rankings | 0.764 | 0.726 |

Recall@5 is the fraction of labelled relevant rows found in the first five results. MRR@5 measures how early the first relevant row appears: first place scores 1, second scores 1/2, and no match in five scores 0. Dense search did best on this small set; combining it with word matching hurt paraphrase retrieval. This is a project regression set, not evidence of general biomedical accuracy. [Labels, full results, and limitations](docs/retrieval.md) are available to inspect.

I can also use dense retrieval inside the answer agent with `uv run omics-rag 'ALB expression in liver' --retrieval embedding --force-agents --json`. Semantic search ranks context; the original SQLite rows still supply every reported measurement. It does not change tissue names used by SQL or make the rule-based answer model understand arbitrary paraphrases.

## Routing questions and exporting reports

I use topics to separate looking up evidence from requesting a saved report:

```sh
uv run omics-rag --topic-agent 'lookup ALB in liver'
uv run omics-rag --topic-agent 'hello'
```

The first command uses the expression knowledge source, backed by the existing text index and SQLite table. The second asks what I want to do. A message matching both topics also asks for clarification before sending anything. Every routing decision is logged with its topic and reason, without the message or webhook URL.

For reports, I start the included flow in one terminal:

```sh
uv run python -m omics_rag.report_flow --definition flows/report-flow.json --output reports
```

In another terminal:

```sh
OMICS_REPORT_WEBHOOK=http://127.0.0.1:8765/report uv run omics-rag \
  --topic-agent 'request a report for ALB in liver' --json
```

The response includes a `report_url`, such as `/reports/<id>.md`. I open `http://127.0.0.1:8765` followed by that path to download the report. The flow selects the public measurements, writes a Markdown file with source links and caveats, and returns its location. I stop the flow with Ctrl-C. Gene-only requests include all available tissues; tissue names must come from `--catalog`.

The YAML [topic file](src/omics_rag/data/topics.yaml) defines trigger phrases, knowledge sources, and the webhook action. The exported [flow definition](flows/report-flow.json) runs with the included local receiver. This is an open-source equivalent of the Copilot Studio pattern of topics, knowledge sources, and flow actions. It is not a Microsoft service or a Power Automate import package. I can point the action at a real HTTP-triggered flow using the same JSON contract; [the setup notes](docs/topics-and-reports.md) explain it. Only configure a trusted endpoint because it receives the report request.

## What an answer means

For `ALB in liver`, the bundled tables report:

| Collection | RNA measurement, nTPM |
| --- | ---: |
| HPA | 198,524 |
| GTEx | 60,543.2 |
| HPA consensus | 198,524 |

nTPM means normalized transcripts per million, a measure of RNA abundance. Each answer links its rows to the original source. HPA and GTEx are separate tissue collections; consensus takes the maximum of the two and is not a third independent experiment. I flag differences of at least twofold and 1 nTPM. That is a comparison rule, not a statistical test.

I use a small, documented extract: 20 genes, 51 distinct tissue names, and 2,540 tissue-level measurements. `uv run omics-rag --catalog` lists what is available. This is for exploring normal-tissue RNA, not diagnosing disease, choosing treatments, or predicting protein levels. A missing gene or tissue is outside this extract, not proof that its expression is zero.

## Using a real local model

I use [Ollama](https://ollama.com/) to run a model locally. With Ollama running:

```sh
ollama pull qwen3:1.7b
uv run omics-rag 'Compare ALB in liver and pancreas' --model qwen3:1.7b --json
```

The model needs tool-calling support, enough memory for its weights, and a 16,384-token context. The mock remains the default so tests do not download a model or require a server. Exact `GENE in tissue` lookups skip the model entirely. Add `--force-agents` to compare that result with the three-agent path.

```sh
uv run omics-rag 'ALB in liver' --force-agents --json
uv run omics-rag 'Compare INS in pancreas and liver' --usage-log usage.jsonl
uv run omics-rag --evaluate
```

The optional usage log contains the question and per-stage prompt hashes, prompt sizes, and token counts. Provider counts are labelled `provider`; the mock uses labelled character estimates. I keep full prompts out of the log. The JSON answer also includes the generated SQL, retrieved descriptions, measurements, citations, and caveats.

## How I split the work

Retrieval-augmented generation (RAG) means finding evidence before producing an answer. I use three separate LangChain agents, each with its own instructions and tool:

1. The retrieval agent ranks descriptions by word overlap or sentence meaning, and finds matching gene records in a local SQLite database.
2. The code-generation agent writes a read-only SQL query to select measurements, compare tissues, or rank them. It can return row IDs only; the database supplies the actual numbers.
3. The synthesis agent merges those rows into a cited answer. Its rendering tool preserves every selected row and calculates disagreement and missing-source warnings, so the model cannot replace numbers or silently drop inconvenient evidence.

The default answer path retains the original TF-IDF source index. The measurement search adds a local FAISS index, a store for 384-number sentence vectors from a pinned, quantized all-MiniLM-L6-v2 model. Hybrid uses reciprocal rank fusion, which combines positions in the two result lists. No embedding API is used. The local model gives the agent path more flexible question interpretation; the mock handles the documented lookup, comparison, ranking, and abstention patterns. I do not treat a passed mock evaluation as a language-model accuracy score.

I describe the boundaries, prompts, and failure behaviour in [the design notes](docs/design.md). [Data notes](docs/data.md) cover the sources, attribution, refresh command, and checksums. [A live model run](docs/live-run.md) records what I actually tested.

## Tests and CI

```sh
uv sync --locked --dev
uv run pytest -q
uv run omics-rag --evaluate
uv run omics-rag --evaluate-retrieval
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv build
```

The suite has 96 tests, including 30 frozen evaluation questions with expected sources and measurements. It also checks unsafe SQL, query budgets, zero versus missing expression, citation coverage, the three tool loops, token accounting, and the cheaper lookup path. New checks cover indexing, FAISS save/reload, offline retrieval, recall and reciprocal-rank calculations, topic routing, fallback, payload validation, and an actual HTTP report export and download. Test servers close their sockets and join their threads before each fixture ends. GitHub Actions runs tests, both evaluations, formatting, and a wheel installation smoke test on Python 3.11 and 3.12. The retrieval tests use frozen vectors and do not download models. Live model inference is a separate manual smoke test because it requires model weights and a running Ollama instance.
