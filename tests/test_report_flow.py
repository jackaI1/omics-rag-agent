import json
import socket
from importlib.resources import files
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from omics_rag.agents import QA
from omics_rag.report_flow import create_server
from omics_rag.topic_agent import TopicAgent


@pytest.fixture
def flow(tmp_path):
    # Exact ownership: this test owns this bound socket and joined thread. No subprocess.
    server = create_server(tmp_path, port=0)
    port = server.server_port
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0


def test_exported_definition_is_packaged():
    assert json.loads(Path("flows/report-flow.json").read_text()) == json.loads(
        files("omics_rag").joinpath("data/report-flow.json").read_text()
    )


def test_routing_through_real_webhook_exports_cited_report(flow):
    base, output = flow
    with QA() as qa:
        result = TopicAgent(qa, webhook_url=base + "/report").ask(
            "request a report for ALB in liver"
        )
    receipt = result["action_result"]
    assert result["topic"] == "report" and "201" in result["answer"]
    assert receipt["rows"] == 3
    with urlopen(base + receipt["report_url"], timeout=5) as response:
        report = response.read().decode()
    assert "60543.2 nTPM" in report
    assert "ALB | liver | hpa" in report
    assert "https://www.proteinatlas.org/" in report
    assert "not an independent replication" in report
    assert len(list(output.glob("*.md"))) == 1


@pytest.mark.parametrize(
    "payload",
    [[], {}, {"request": 7, "source": "omics-rag-agent"}, {"request": "ALB", "source": "wrong"}],
)
def test_invalid_payload_does_not_write_report(flow, payload):
    base, output = flow
    with pytest.raises(HTTPError) as error:
        urlopen(Request(base + "/report", data=json.dumps(payload).encode()), timeout=5)
    assert error.value.code == 400
    assert list(output.iterdir()) == []


def test_report_refuses_missing_gene(flow):
    base, output = flow
    with pytest.raises(HTTPError) as error:
        urlopen(
            Request(
                base + "/report",
                data=json.dumps(
                    {"request": "request a report", "source": "omics-rag-agent"}
                ).encode(),
            ),
            timeout=5,
        )
    assert error.value.code == 422
    assert list(output.iterdir()) == []


def test_report_paths_cannot_escape_output(flow):
    base, _ = flow
    with pytest.raises(HTTPError) as error:
        urlopen(base + "/reports/../../pyproject.toml", timeout=5)
    assert error.value.code == 404


def test_unknown_tissue_requires_clarification(flow):
    base, output = flow
    with pytest.raises(HTTPError) as error:
        urlopen(
            Request(
                base + "/report",
                data=json.dumps(
                    {"request": "request a report for ALB in Atlantis", "source": "omics-rag-agent"}
                ).encode(),
            ),
            timeout=5,
        )
    assert error.value.code == 422
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("body", [b"not json", b"x" * 16385])
def test_malformed_or_oversized_request_is_rejected(flow, body):
    base, output = flow
    with pytest.raises(HTTPError) as error:
        urlopen(Request(base + "/report", data=body), timeout=5)
    assert error.value.code == 400
    assert list(output.iterdir()) == []
