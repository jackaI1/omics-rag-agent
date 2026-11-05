"""A deterministic tool-calling mock and per-stage prompt accounting."""

import hashlib
import json
import math
import re
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

PROMPT_VERSION = "1"


class Usage(BaseCallbackHandler):
    def __init__(self, stage):
        self.stage = stage
        self.calls = []

    def on_chat_model_start(self, serialized, messages, **kwargs):
        prompt = "\n".join(str(m.content) for group in messages for m in group)
        self.calls.append(
            {
                "stage": self.stage,
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "prompt_chars": len(prompt),
                "input_tokens": math.ceil(len(prompt) / 4),
                "output_tokens": 0,
                "token_basis": "character_estimate",
            }
        )

    def on_llm_end(self, response, **kwargs):
        message = response.generations[0][0].message
        record = self.calls[-1]
        if message.usage_metadata:
            record.update(
                input_tokens=message.usage_metadata["input_tokens"],
                output_tokens=message.usage_metadata["output_tokens"],
                token_basis="provider",
            )
        else:
            record["output_tokens"] = math.ceil(
                len(str(message.content) + str(message.tool_calls)) / 4
            )


class MockModel(BaseChatModel):
    """Rule-based fixture, explicitly not a learned model or a scientific oracle."""

    @property
    def _llm_type(self):
        return "deterministic-omics-mock"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        if isinstance(messages[-1], ToolMessage):
            message = AIMessage(content="Tool result accepted.")
        else:
            payload = json.loads(messages[-1].content)
            role = payload["role"]
            question = payload["question"]
            if role == "retrieval":
                name, args = "retrieve_evidence", {"query": question, "genes": payload["genes"]}
            elif role == "code":
                genes = payload["genes"]
                tissues = payload["tissues"]
                if not genes or (
                    not tissues
                    and not re.search(r"\b(top|highest|rank)\b", question, re.IGNORECASE)
                ):
                    sql = "SELECT id FROM expression WHERE 0"
                else:
                    quoted = ",".join("'" + g.replace("'", "''") + "'" for g in genes)
                    sql = f"SELECT id FROM expression WHERE gene IN ({quoted})"
                    if tissues:
                        quoted_tissues = ",".join("'" + t.replace("'", "''") + "'" for t in tissues)
                        sql += f" AND tissue IN ({quoted_tissues})"
                    if re.search(r"\b(top|highest|rank)\b", question, re.IGNORECASE):
                        count = re.search(r"\btop (\d+)\b", question, re.IGNORECASE)
                        limit = min(int(count.group(1)), 10) if count else 5
                        sql += f" AND source='consensus' ORDER BY ntpm DESC, tissue LIMIT {limit}"
                    else:
                        sql += " ORDER BY gene, tissue, source LIMIT 100"
                name, args = "run_expression_sql", {"sql": sql}
            else:
                name, args = (
                    "compose_answer",
                    {"evidence_ids": payload["evidence_ids"], "layout": "by_tissue"},
                )
            message = AIMessage(
                content="",
                tool_calls=[{"name": name, "args": args, "id": "mock-call", "type": "tool_call"}],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])
