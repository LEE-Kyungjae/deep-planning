#!/usr/bin/env python3
import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Any, Dict, Optional

from deepplan_agent import execute_tool, list_tools, natural_language_to_tool


class DeepPlanHandler(BaseHTTPRequestHandler):
    server_version = "DeepPlanHTTP/0.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/plan":
            self._write_json(HTTPStatus.OK, execute_tool("get_plan", {}))
            return
        if path == "/qa":
            self._write_json(HTTPStatus.OK, execute_tool("get_qa", {}))
            return
        if path == "/tools":
            self._write_json(HTTPStatus.OK, {"tools": list_tools()})
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        payload = self._read_json()
        if payload is None:
            return
        path = urlparse(self.path).path

        if path == "/plan":
            self._write_json(HTTPStatus.OK, execute_tool("update_plan", payload))
            return

        if path == "/evidence":
            try:
                self._write_json(HTTPStatus.OK, execute_tool("add_evidence", payload))
            except ValueError as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        if path == "/agent/act":
            prompt = str(payload.get("input", "")).strip()
            if not prompt:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "input is required"})
                return
            try:
                tool_name, tool_input = natural_language_to_tool(prompt)
                result = execute_tool(tool_name, tool_input)
            except ValueError as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._write_json(HTTPStatus.OK, {"tool": tool_name, "input": tool_input, "result": result})
            return

        if path.startswith("/tools/"):
            tool_name = path.split("/", 2)[2].strip()
            tool_input = payload.get("input", payload)
            if not isinstance(tool_input, dict):
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "tool input must be a JSON object"})
                return
            try:
                result = execute_tool(tool_name, tool_input)
            except ValueError as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._write_json(HTTPStatus.OK, {"tool": tool_name, "input": tool_input, "result": result})
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> Optional[Dict[str, Any]]:
        length = self.headers.get("Content-Length", "0")
        try:
            raw_length = int(length)
        except ValueError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return None

        body = self.rfile.read(raw_length) if raw_length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return None
        if not isinstance(payload, dict):
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "json_body_must_be_object"})
            return None
        return payload

    def _write_json(self, status: HTTPStatus, payload: Dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeepPlan minimal HTTP service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DeepPlanHandler)
    print(f"DeepPlan service listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
