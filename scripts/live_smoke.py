"""Run a real local model and check its answer against frozen source facts."""

import argparse
import json
from pathlib import Path

from langchain_ollama import ChatOllama

from omics_rag.agents import QA
from omics_rag.evaluation import cases, check

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="qwen3:1.7b")
parser.add_argument("--base-url", default="http://localhost:11434")
parser.add_argument("--output", type=Path)
args = parser.parse_args()
model = ChatOllama(
    model=args.model,
    base_url=args.base_url,
    temperature=0,
    num_ctx=16384,
    num_predict=1024,
    keep_alive=0,
    reasoning=False,
)
case = next(c for c in cases() if c["id"] == "q11")
with QA(model) as qa:
    result = qa.ask(case["question"])
errors = check(result, case)
if errors:
    raise SystemExit("Live evidence check failed: " + ", ".join(errors))
if not result["usage"] or any(u["token_basis"] != "provider" for u in result["usage"]):
    raise SystemExit("Missing provider token counts")
if args.output:
    args.output.write_text(json.dumps(result, indent=2) + "\n")
print(
    f"PASS: {len(result['rows'])} cited rows; {len(result['usage'])} model calls; {result['total_tokens']} provider tokens"
)
