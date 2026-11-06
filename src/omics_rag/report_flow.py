"""Run the exported HTTP-triggered report workflow without a Microsoft account."""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from .agents import synthesize
from .store import Store


def create_server(output, host="127.0.0.1", port=8765, definition=None):
    flow = definition or json.loads(
        files("omics_rag").joinpath("data/report-flow.json").read_text()
    )
    if flow["actions"] != ["select_expression_rows", "render_cited_markdown", "write_report"]:
        raise ValueError("Unsupported report flow actions")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # The message, query and webhook URL do not belong in access logs.

        def respond(self, status, body, content_type="application/json"):
            data = (
                json.dumps(body).encode() if content_type == "application/json" else body.encode()
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != flow["trigger"]["path"]:
                self.respond(404, {"error": "Unknown flow"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= flow["trigger"]["max_bytes"]:
                    raise ValueError("Request must have a bounded Content-Length")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or any(
                    key not in payload for key in flow["trigger"]["required"]
                ):
                    raise ValueError("Missing request or source")
                if payload["source"] != flow["trigger"]["source"]:
                    raise ValueError("Unknown request source")
                message = payload["request"]
                if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
                    raise ValueError("Request must contain 1 to 2000 characters")
            except (ValueError, TypeError):
                self.respond(400, {"error": "Invalid report payload"})
                return
            store = Store()
            try:
                genes, tissues = store.entities(message)
                if not genes:
                    self.respond(422, {"error": "Name a gene from the expression catalog"})
                    return
                if not tissues and re.search(r"\bin\b", message, re.IGNORECASE):
                    self.respond(422, {"error": "Name a tissue from the expression catalog"})
                    return
                rows = [
                    r
                    for r in store.rows.values()
                    if r["gene"] in genes and (not tissues or r["tissue"] in tissues)
                ]
                if not rows:
                    self.respond(422, {"error": "No matching measurements in the extract"})
                    return
                report = synthesize(store, rows)
                report_id = uuid4().hex
                filename = f"{report_id}.md"
                (output / filename).write_text(
                    "# Expression report\n\n" + report["answer"] + "\n", encoding="utf-8"
                )
                self.respond(
                    flow["response"]["status"],
                    {
                        "report_id": report_id,
                        "report_url": f"/reports/{filename}",
                        "rows": len(rows),
                    },
                )
            finally:
                store.close()

        def do_GET(self):
            match = re.fullmatch(r"/reports/([a-f0-9]{32}\.md)", self.path)
            path = output / match[1] if match else None
            if path is None or not path.is_file():
                self.respond(404, {"error": "Report not found"})
                return
            self.respond(200, path.read_text(encoding="utf-8"), "text/markdown; charset=utf-8")

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--definition", type=Path)
    args = parser.parse_args()
    definition = json.loads(args.definition.read_text()) if args.definition else None
    with create_server(args.output, args.host, args.port, definition) as server:
        print(
            f"Report flow listening on http://{args.host}:{server.server_port}/report", flush=True
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
