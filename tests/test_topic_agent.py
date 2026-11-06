import json
import logging
from unittest.mock import patch

import pytest

from omics_rag.agents import QA
from omics_rag.topic_agent import TopicAgent


def test_routes_knowledge_and_logs(caplog):
    with QA() as qa, caplog.at_level(logging.INFO):
        result = TopicAgent(qa).ask("lookup ALB in liver")
        assert result["topic"] == "expression"
        assert len(result["rows"]) == 3
        assert "expression" in caplog.text


def test_fallback_and_ambiguity(caplog):
    with QA() as qa, caplog.at_level(logging.INFO):
        agent = TopicAgent(qa)
        assert agent.ask("hello")["topic"] is None
        assert agent.ask("request a report about expression")["topic"] is None
        assert "ambiguous" in caplog.text
        assert "no_match" in caplog.text
        assert "request a report about expression" not in caplog.text


def test_report_action_payload():
    class Response:
        status = 202

        def read(self, limit):
            return b'{"report_id":"example"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with QA() as qa, patch("omics_rag.topic_agent.urlopen", return_value=Response()) as send:
        result = TopicAgent(qa, webhook_url="https://example.test/flow").ask(
            "request a report for ALB"
        )
        request = send.call_args.args[0]
        assert request.method == "POST"
        assert json.loads(request.data) == {
            "request": "request a report for ALB",
            "source": "omics-rag-agent",
        }
        assert "202" in result["answer"]


def test_report_requires_configured_endpoint():
    with QA() as qa, patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="OMICS_REPORT_WEBHOOK"):
            TopicAgent(qa).ask("request a report")


@pytest.mark.parametrize("message", ["", " ", "x" * 2001, None])
def test_input_validation(message):
    with QA() as qa:
        with pytest.raises(ValueError, match="1 to 2000"):
            TopicAgent(qa).ask(message)


def test_trigger_boundaries_and_no_side_effect_on_ambiguity():
    with QA() as qa, patch("omics_rag.topic_agent.urlopen") as send:
        agent = TopicAgent(qa, webhook_url="http://127.0.0.1/report")
        assert agent.ask("unranked")["topic"] is None
        assert agent.ask("request a report and compare ALB")["topic"] is None
        send.assert_not_called()


def test_unknown_configured_knowledge_source_is_rejected():
    config = {
        "knowledge_sources": {"bad": ["unknown"]},
        "topics": [{"id": "bad", "triggers": ["hello"], "knowledge": "bad"}],
        "fallback": "clarify",
    }
    with QA() as qa, pytest.raises(ValueError, match="knowledge source"):
        TopicAgent(qa, config=config)
