import json
import subprocess
import sys

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from omics_rag.agents import QA, synthesize
from omics_rag.evaluation import cases, check
from omics_rag.models import MockModel, Usage


@pytest.fixture(scope="module")
def qa():
    with QA() as instance:
        yield instance


@pytest.mark.parametrize("case", cases(), ids=lambda c: c["id"])
def test_frozen_evaluation(qa, case):
    result = qa.ask(case["question"], force_agents=case["force_agents"])
    assert not check(result, case)


def test_three_real_tool_agent_loops_and_usage(qa):
    result = qa.ask("Compare ALB in liver and pancreas")
    assert result["route"] == "agents"
    assert [u["stage"] for u in result["usage"]] == ["retrieval"] * 2 + ["code"] * 2 + [
        "synthesis"
    ] * 2
    assert all(u["input_tokens"] > 0 and u["output_tokens"] > 0 for u in result["usage"])
    assert all(u["token_basis"] == "character_estimate" for u in result["usage"])
    assert len({u["prompt_sha256"] for u in result["usage"]}) == 6
    assert result["total_tokens"] == sum(
        u["input_tokens"] + u["output_tokens"] for u in result["usage"]
    )
    assert result["sql"].startswith("SELECT id FROM expression")
    assert len(result["retrieved_documents"]) == 3
    assert any("Disagreement: ALB in liver" in f for f in result["flags"])


def test_fast_lookup_matches_agents_without_model_tokens(qa):
    fast = qa.ask("ALB in liver")
    full = qa.ask("ALB in liver", force_agents=True)
    assert fast["rows"] == full["rows"]
    assert fast["citations"] == full["citations"]
    assert fast["total_tokens"] == 0 < full["total_tokens"]
    assert fast["usage"] == []


def test_case_and_multiple_genes(qa):
    result = qa.ask("Compare alb and ins in liver")
    assert {r["gene"] for r in result["rows"]} == {"ALB", "INS"}
    assert len(result["rows"]) == 6


def test_explicit_zero_is_not_missing(qa):
    row = next(r for r in qa.store.rows.values() if r["ntpm"] == 0)
    result = synthesize(qa.store, [row])
    assert "0 nTPM" in result["answer"]
    assert len(result["rows"]) == 1


def test_near_agreement_not_flagged(qa):
    rows = [
        dict(id=1, gene="TEST", tissue="liver", source="hpa", ntpm=10, ensembl="x"),
        dict(id=2, gene="TEST", tissue="liver", source="gtex", ntpm=12, ensembl="x"),
    ]
    assert not any(f.startswith("Disagreement") for f in synthesize(qa.store, rows)["flags"])


def test_provider_token_counts(qa):
    tracker = Usage("test")
    tracker.on_chat_model_start({}, [[AIMessage(content="test")]])
    message = AIMessage(
        content="done", usage_metadata={"input_tokens": 17, "output_tokens": 4, "total_tokens": 21}
    )
    tracker.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]))
    assert tracker.calls[0]["token_basis"] == "provider"
    assert tracker.calls[0]["input_tokens"] == 17
    assert tracker.calls[0]["output_tokens"] == 4


@pytest.mark.parametrize("question", ["", " ", "x" * 2001])
def test_input_bounds(qa, question):
    with pytest.raises(ValueError, match="1 to 2000"):
        qa.ask(question)


def test_silent_model_fails_closed():
    class SilentModel(MockModel):
        def _generate(self, messages, **kwargs):
            from langchain_core.outputs import ChatResult

            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="42"))])

    with QA(SilentModel()) as qa:
        with pytest.raises(ValueError, match="did not return evidence"):
            qa.ask("Compare ALB in liver and pancreas")


def test_cli_json_and_local_usage_log(tmp_path):
    log = tmp_path / "usage.jsonl"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "omics_rag.cli",
            "INS in pancreas",
            "--json",
            "--usage-log",
            str(log),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(run.stdout)
    assert result["route"] == "exact_lookup"
    assert json.loads(log.read_text())["total_tokens"] == 0


def test_code_agent_can_correct_rejected_sql():
    class CorrectingModel(MockModel):
        def _generate(self, messages, **kwargs):
            from langchain_core.messages import ToolMessage
            from langchain_core.outputs import ChatResult

            if isinstance(messages[-1], ToolMessage) and "SELECT id only" in str(
                messages[-1].content
            ):
                message = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "run_expression_sql",
                            "args": {
                                "sql": "SELECT id FROM expression WHERE gene='ALB' AND tissue IN ('liver','pancreas') ORDER BY tissue,source LIMIT 100"
                            },
                            "id": "retry",
                            "type": "tool_call",
                        }
                    ],
                )
                return ChatResult(generations=[ChatGeneration(message=message)])
            if messages[-1].type == "human" and json.loads(messages[-1].content)["role"] == "code":
                message = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "run_expression_sql",
                            "args": {"sql": "SELECT ntpm FROM expression LIMIT 1"},
                            "id": "bad-select",
                            "type": "tool_call",
                        }
                    ],
                )
                return ChatResult(generations=[ChatGeneration(message=message)])
            return super()._generate(messages, **kwargs)

    with QA(CorrectingModel()) as qa:
        result = qa.ask("Compare ALB in liver and pancreas")
        assert len(result["rows"]) == 6
        assert len([u for u in result["usage"] if u["stage"] == "code"]) == 3


def test_synthesis_cannot_omit_evidence():
    class OmittingModel(MockModel):
        def _generate(self, messages, **kwargs):
            from langchain_core.outputs import ChatResult

            if (
                messages[-1].type == "human"
                and json.loads(messages[-1].content)["role"] == "synthesis"
            ):
                message = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "compose_answer",
                            "args": {"evidence_ids": [], "layout": "by_tissue"},
                            "id": "omit",
                            "type": "tool_call",
                        }
                    ],
                )
                return ChatResult(generations=[ChatGeneration(message=message)])
            return super()._generate(messages, **kwargs)

    with QA(OmittingModel()) as qa:
        with pytest.raises(ValueError, match="preserve every supplied"):
            qa.ask("Compare ALB in liver and pancreas")
