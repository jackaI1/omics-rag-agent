"""Frozen measurements and expected sources, not model-graded answers."""

import json
from importlib.resources import files


def cases():
    return json.loads(files("omics_rag").joinpath("data/evaluation.json").read_text())


def check(result, case):
    actual = sorted((r["source"], r["gene"], r["tissue"], r["ntpm"]) for r in result["rows"])
    expected = sorted(
        (r["source"], r["gene"], r["tissue"], r["ntpm"]) for r in case["expected_measurements"]
    )
    errors = []
    if actual != expected:
        errors.append("measurements")
    if sorted({c["source"] for c in result["citations"]}) != case["expected_sources"]:
        errors.append("sources")
    if len(result["citations"]) != len(result["rows"]) or any(
        f"[row:{r['id']}]" not in result["answer"] for r in result["rows"]
    ):
        errors.append("citation coverage")
    missing = any(f.startswith("Missing") for f in result["flags"])
    if missing != case["expected_missing"]:
        errors.append("missing evidence flag")
    return errors


def evaluate(qa):
    results = []
    for case in cases():
        try:
            answer = qa.ask(case["question"], force_agents=case["force_agents"])
            errors = check(answer, case)
            results.append(
                {
                    "id": case["id"],
                    "passed": not errors,
                    "errors": errors,
                    "route": answer["route"],
                    "tokens": answer["total_tokens"],
                }
            )
        except Exception as error:
            results.append({"id": case["id"], "passed": False, "errors": [str(error)]})
    return {
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "model": qa.model._llm_type,
        "results": results,
    }
