# Topics, knowledge, and a report action

I built a way to save gene activity comparisons because I wanted the numbers and their sources together when I returned to a question. The public tables measure RNA abundance, which helps show where a gene is active in normal human tissues. A report keeps the published values, links to their source tables, and warnings when collections disagree or evidence is missing. It does not turn these measurements into a diagnosis.

For example, `request a report for ALB in liver` saves the available liver measurements for the ALB gene. The response tells me where to download the report. The same interface can answer a lookup without saving a file; the topic decides which of those two jobs I asked for.

I use the same broad structure as Copilot Studio: topics decide what a message means, knowledge sources supply evidence, and an action starts a workflow. This is my own open-source implementation. I have not deployed it in Microsoft's product or tested a Microsoft tenant.

`src/omics_rag/data/topics.yaml` is the declarative configuration. The expression topic references the existing TF-IDF index and SQLite store through `QA`. The report topic calls an HTTP action. Trigger phrases match whole words, ignoring case. My confidence rule is conservative: exactly one topic with an explicit trigger must match. Zero or multiple topic matches return the configured clarification, with no action. It is not a learned intent classifier. For example, `request a report about expression` deliberately needs clarification.

Every valid message produces a structured `topic_route` log with the chosen topic, matched topic IDs, and `trigger_match`, `no_match`, or `ambiguous` reason. It excludes message text and the endpoint URL. The CLI enables these logs on stderr; normal Python callers can attach their own logging handler.

## Two-minute local report setup

From the checkout, start the receiver:

```sh
uv sync --locked
uv run python -m omics_rag.report_flow --definition flows/report-flow.json --output reports
```

In another terminal, send a report request:

```sh
OMICS_REPORT_WEBHOOK=http://127.0.0.1:8765/report uv run omics-rag \
  --topic-agent 'request a report for ALB in liver' --json
```

The HTTP action sends this JSON with `Content-Type: application/json` and a ten-second timeout:

```json
{"request": "request a report for ALB in liver", "source": "omics-rag-agent"}
```

The included receiver returns HTTP 201 and a receipt:

```json
{"report_id": "<generated ID>", "report_url": "/reports/<generated ID>.md", "rows": 3}
```

Open `http://127.0.0.1:8765` plus the returned `report_url`, or read the file in `reports/`. The report contains original measurements, source citations, and the same missing-evidence and disagreement caveats as the answer renderer. It does not include unverified generated prose. A gene-only request exports all available tissues for that gene. A request without a known gene, or with an unrecognized tissue after “in”, returns HTTP 422 and writes no report. Stop the receiver with Ctrl-C; delete `reports/` when finished. Those files are ignored by git.

`flows/report-flow.json` is the portable workflow export, with its HTTP trigger, required input fields, ordered actions, and response contract. The included runner reads it, selects SQLite rows, renders cited Markdown, writes the file, and serves the download. A byte-equivalent packaged copy lets the installed wheel run without the checkout. This definition is for the local runner, not an importable Microsoft Power Automate package.

The receiver binds to localhost by default and has no authentication or retention policy. It is a development flow, not a public production service. It accepts at most 16 KB per request. It serves only generated report IDs, preventing arbitrary file paths. Tests use an operating-system-assigned port, shut down and close the server, join its thread, and verify that its port refuses connections afterward.

## Connecting a separately hosted flow

I can create an HTTP-triggered Power Automate flow, or use another trusted receiver, with `request` and `source` as required string fields. It must accept the contract above and return an empty successful response or a JSON receipt. A typical Microsoft flow would call the expression service and create a file in its configured storage; the local runner is the complete account-free demonstration of those steps.

I set `OMICS_REPORT_WEBHOOK` to the endpoint URL in my shell. The URL and any credential embedded in it stay outside the repository. Requests contain the original report message, so only a trusted endpoint should receive them. Non-success HTTP status, network errors, and oversized responses fail the command; there is no success-shaped fallback or automatic retry that could duplicate report creation. Only the local flow is covered by the end-to-end test; no Microsoft account is required or claimed.

## Where I change the configuration

| File | What I use it for |
| --- | --- |
| [Topic configuration](../src/omics_rag/data/topics.yaml) | Change trigger phrases, knowledge source names, and the report action. |
| [Labelled retrieval questions](../src/omics_rag/data/retrieval-queries.json) | Inspect the explicit gene, tissue, and source targets used to compare search methods. |
| [Report flow export](../flows/report-flow.json) | Inspect the local receiver's HTTP contract and ordered report steps. |
| [Routing tests](../tests/test_topic_agent.py) | Check topic matches, clarification, logs, and the outbound request. |
| [Report tests](../tests/test_report_flow.py) | Check the actual report export, download, and server cleanup. |
