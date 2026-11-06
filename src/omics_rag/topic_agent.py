"""Declarative topic routing for the expression assistant."""

import json
import logging
import os
import re
from importlib.resources import files
from urllib.request import Request, urlopen

import yaml

logger = logging.getLogger(__name__)


class TopicAgent:
    def __init__(self, qa, config=None, webhook_url=None):
        self.qa = qa
        self.config = config or yaml.safe_load(
            files("omics_rag").joinpath("data/topics.yaml").read_text()
        )
        known = {"tfidf", "sqlite", "embedding", "faiss"}
        for topic in self.config["topics"]:
            if not topic.get("triggers"):
                raise ValueError("Topic needs trigger phrases")
            if "knowledge" in topic:
                sources = self.config["knowledge_sources"].get(topic["knowledge"])
                if not sources or set(sources) - known or "sqlite" not in sources:
                    raise ValueError("Unknown or incomplete knowledge source")
            elif topic.get("action") != "report_webhook":
                raise ValueError("Unknown topic action")
        self.webhook_url = webhook_url or os.environ.get("OMICS_REPORT_WEBHOOK")

    def route(self, message):
        text = message.casefold()
        matches = []
        for topic in self.config["topics"]:
            if any(
                re.search(r"(?<!\w)" + re.escape(t.casefold()) + r"(?!\w)", text)
                for t in topic["triggers"]
            ):
                matches.append(topic)
        # Ambiguous requests require clarification rather than choosing an action.
        topic = matches[0] if len(matches) == 1 else None
        logger.info(
            json.dumps(
                {
                    "event": "topic_route",
                    "topic": topic["id"] if topic else None,
                    "reason": "trigger_match" if topic else "ambiguous" if matches else "no_match",
                    "matches": [item["id"] for item in matches],
                }
            )
        )
        return topic

    def ask(self, message):
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise ValueError("Question must contain 1 to 2000 characters")
        topic = self.route(message)
        if topic is None:
            return {"topic": None, "answer": self.config["fallback"]}
        if topic.get("action") == "report_webhook":
            if not self.webhook_url:
                raise ValueError("Set OMICS_REPORT_WEBHOOK to the report flow URL")
            payload = {"request": message, "source": "omics-rag-agent"}
            request = Request(
                self.webhook_url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                status = response.status
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Report response exceeds 64 KB")
                receipt = json.loads(raw) if raw else {}
            return {
                "topic": topic["id"],
                "answer": f"Report request sent (HTTP {status}).",
                "action_result": receipt,
            }
        if topic.get("knowledge") != "expression":
            raise ValueError("Unknown knowledge source")
        return {"topic": topic["id"], **self.qa.ask(message)}
