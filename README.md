# omics-rag-agent

I built a question-answering tool for public gene expression data because I wanted to learn how to find and compare measurements without manually searching through tables. It is a personal learning project: I can ask about a gene and tissue, see the measurements and follow their links back to the sources.

To try it, install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run:

```sh
git clone https://github.com/jackaI1/omics-rag-agent.git
cd omics-rag-agent
uv sync --locked --dev
uv run omics-rag 'ACTB transcript levels in cardiac tissue' --search --retrieval embedding
```

The same project is also in my [lab-assay-lims collection](https://github.com/jackaI1/lab-assay-lims/tree/main/projects/omics-rag-agent). To use that copy, clone `lab-assay-lims` and enter `projects/omics-rag-agent` before running the same `uv sync` and `uv run` commands. Both copies include the cached data needed for the examples, and each has its own CI checks.

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

I describe the boundaries, prompts, and failure behaviour in [the design notes](docs/design.md). [Data notes](docs/data.md) cover the sources, attribution, refresh command, and checksums. [A live model run](docs/live-run.md) records what I actually tested.

## Tests and limits

Run `uv run pytest -q` to check the project. The suite has 96 tests, including offline retrieval, topic routing and an HTTP report download. GitHub Actions runs the tests, evaluations and an installed-package check on Python 3.11 and 3.12. The project collection has its own workflow for this project.
