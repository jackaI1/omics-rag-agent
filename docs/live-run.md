# A real local model run

I ran the three-agent path on November 5, 2026 with Ollama and `qwen3:1.7b` (local model ID `8f68893c685c`). I used the checked-in HPA extract and the exact dependencies in `uv.lock`. The question was:

> Compare ALB in liver and pancreas

I ran:

```sh
ollama pull qwen3:1.7b
uv run omics-rag 'Compare ALB in liver and pancreas' --model qwen3:1.7b --json
```

The [recorded JSON result](live-run.json) contains the actual retrieved descriptions, selected rows, citations, prompt hashes and provider token counts. I checked it against frozen evaluation case `q11`: all six measurements, all three expected source IDs, citation coverage, and missing-evidence behaviour matched. The generated query was:

```sql
SELECT id FROM expression
WHERE gene='ALB' AND tissue IN ('liver','pancreas')
ORDER BY tissue,source LIMIT 100
```

| Stage | Model calls | Input tokens | Output tokens |
| --- | ---: | ---: | ---: |
| Retrieval | 3 | 2,490 | 217 |
| Code generation | 3 | 7,497 | 483 |
| Synthesis | 2 | 2,824 | 461 |
| Total | 8 | 12,811 | 1,161 |

The total was 13,972 provider-reported tokens. Counts include repeated calls and tool-result messages. The first trial before I added SQL correction feedback was rejected because the model selected extra columns. In the recorded successful run, the code agent corrected a rejected query after seeing the tool error. The final answer retained all six rows and flagged the HPA/GTEx differences in both tissues.

This is one successful local-model smoke test, not a 30/30 live-model benchmark. The 30/30 result in CI is explicitly the deterministic mock evaluation. Small models can still choose incorrect filters or exceed a step limit. I expose the SQL and evidence for inspection, reject invalid execution, and keep clinical interpretation out of the answer.

To repeat the same live check with assertions:

```sh
uv run python scripts/live_smoke.py --model qwen3:1.7b --output /tmp/live-answer.json
```

The script exits nonzero on a measurement, citation, source, or token-accounting mismatch. Token counts can vary across model/server versions. The CLI sets `keep_alive=0`; after the run I confirmed `ollama ps` had no loaded models. I reused the existing local Ollama server and did not launch a browser or disposable server.
