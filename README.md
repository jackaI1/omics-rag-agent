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

1. The retrieval agent searches a vector index, which ranks dataset descriptions by text similarity, and finds matching gene records in a local SQLite database.
2. The code-generation agent writes a read-only SQL query to select measurements, compare tissues, or rank them. It can return row IDs only; the database supplies the actual numbers.
3. The synthesis agent merges those rows into a cited answer. Its rendering tool preserves every selected row and calculates disagreement and missing-source warnings, so the model cannot replace numbers or silently drop inconvenient evidence.

The vector index uses local TF-IDF word vectors. It needs no embedding API, but it matches words rather than understanding synonyms. The local model gives the agent path more flexible question interpretation; the mock handles the documented lookup, comparison, ranking, and abstention patterns. I do not treat a passed mock evaluation as a language-model accuracy score.

I describe the boundaries, prompts, and failure behaviour in [the design notes](docs/design.md). [Data notes](docs/data.md) cover the sources, attribution, refresh command, and checksums. [A live model run](docs/live-run.md) records what I actually tested.

## Tests and CI

```sh
uv sync --locked --dev
uv run pytest -q
uv run omics-rag --evaluate
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv build
```

The suite has 58 tests, including 30 frozen evaluation questions with expected sources and measurements. It also checks unsafe SQL, query budgets, zero versus missing expression, citation coverage, the three tool loops, token accounting, and the cheaper lookup path. GitHub Actions runs tests, evaluation, formatting, and a wheel installation smoke test on Python 3.11 and 3.12. Live model inference is a separate manual smoke test because it requires model weights and a running Ollama instance.
