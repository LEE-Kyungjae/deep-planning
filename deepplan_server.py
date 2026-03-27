#!/usr/bin/env python3
import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict, Optional

from deepplan_agent import execute_tool, list_tools, natural_language_to_tool
from deepplan import PlanConflictError, cycle_snapshot, normalize_fingerprint


class DeepPlanHandler(BaseHTTPRequestHandler):
    server_version = "DeepPlanHTTP/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/health":
            result = execute_tool("get_health", {})
            status = HTTPStatus.OK if result.get("status") == "ok" else HTTPStatus.SERVICE_UNAVAILABLE if result.get("status") == "error" else HTTPStatus.OK
            self._write_json(status, result)
            return
        if path == "/plan":
            result = execute_tool("get_plan", {})
            self._write_json(HTTPStatus.OK, result, extra_headers={"ETag": self._format_etag(result["fingerprint"])})
            return
        if path == "/qa":
            self._write_json(HTTPStatus.OK, execute_tool("get_qa", {}))
            return
        if path == "/cycle":
            try:
                history_limit = int(query.get("limit", ["10"])[0])
            except ValueError:
                self._write_error(HTTPStatus.BAD_REQUEST, "limit must be an integer")
                return
            if history_limit < 0:
                self._write_error(HTTPStatus.BAD_REQUEST, "limit must be non-negative")
                return
            result = cycle_snapshot(history_limit=history_limit)
            self._write_json(HTTPStatus.OK, result, extra_headers={"ETag": self._format_etag(result["fingerprint"])})
            return
        if path == "/history":
            self._write_json(HTTPStatus.OK, execute_tool("get_history", {}))
            return
        if path == "/validate":
            self._write_json(HTTPStatus.OK, execute_tool("validate_plan", {}))
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
        expected_fingerprint = self._expected_fingerprint()

        if path == "/plan":
            self._execute_tool_json("update_plan", payload, expected_fingerprint)
            return

        if path == "/evidence":
            self._execute_tool_json("add_evidence", payload, expected_fingerprint)
            return

        if path == "/replan":
            self._execute_tool_json("replan", payload, expected_fingerprint)
            return

        if path == "/restore/preview":
            self._execute_tool_json("preview_restore", payload, None)
            return

        if path == "/restore":
            self._execute_tool_json("restore_revision", payload, expected_fingerprint)
            return

        if path == "/agent/act":
            prompt = str(payload.get("input", "")).strip()
            if not prompt:
                self._write_error(HTTPStatus.BAD_REQUEST, "input is required")
                return
            try:
                tool_name, tool_input = natural_language_to_tool(prompt)
                self._merge_expected_fingerprint(tool_input, expected_fingerprint)
                result = execute_tool(tool_name, tool_input)
            except PlanConflictError as exc:
                self._write_error(HTTPStatus.PRECONDITION_FAILED, str(exc), current_fingerprint=exc.current_fingerprint)
                return
            except ValueError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except Exception as exc:
                self._write_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc), kind="internal_error")
                return
            headers = self._etag_headers(result.get("fingerprint"))
            self._write_json(HTTPStatus.OK, {"tool": tool_name, "input": tool_input, "result": result}, extra_headers=headers)
            return

        if path.startswith("/tools/"):
            tool_name = path.split("/", 2)[2].strip()
            tool_input = payload.get("input", payload)
            if not isinstance(tool_input, dict):
                self._write_error(HTTPStatus.BAD_REQUEST, "tool input must be a JSON object")
                return
            self._merge_expected_fingerprint(tool_input, expected_fingerprint)
            self._execute_tool_wrapper(tool_name, tool_input)
            return

        self._write_error(HTTPStatus.NOT_FOUND, "not_found", kind="not_found")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> Optional[Dict[str, Any]]:
        length = self.headers.get("Content-Length", "0")
        try:
            raw_length = int(length)
        except ValueError:
            self._write_error(HTTPStatus.BAD_REQUEST, "invalid_content_length")
            return None

        if raw_length <= 0:
            self._write_error(HTTPStatus.BAD_REQUEST, "empty_body")
            return None

        body = self.rfile.read(raw_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._write_error(HTTPStatus.BAD_REQUEST, "invalid_json")
            return None
        if not isinstance(payload, dict):
            self._write_error(HTTPStatus.BAD_REQUEST, "json_body_must_be_object")
            return None
        return payload

    def _expected_fingerprint(self) -> Optional[str]:
        header = self.headers.get("If-Match", "")
        normalized = normalize_fingerprint(header)
        return normalized or None

    def _merge_expected_fingerprint(self, payload: Dict[str, Any], expected_fingerprint: Optional[str]) -> None:
        if expected_fingerprint and "expected_fingerprint" not in payload:
            payload["expected_fingerprint"] = expected_fingerprint

    def _format_etag(self, fingerprint: str) -> str:
        return f'"{fingerprint}"'

    def _etag_headers(self, fingerprint: Optional[str]) -> Dict[str, str]:
        if not fingerprint:
            return {}
        return {"ETag": self._format_etag(str(fingerprint))}

    def _write_error(
        self,
        status: HTTPStatus,
        message: str,
        *,
        kind: str = "error",
        current_fingerprint: Optional[str] = None,
    ) -> None:
        payload: Dict[str, Any] = {"error": message, "type": kind}
        if current_fingerprint:
            payload["current_fingerprint"] = current_fingerprint
        self._write_json(status, payload, extra_headers=self._etag_headers(current_fingerprint))

    def _execute_tool_json(self, tool_name: str, payload: Dict[str, Any], expected_fingerprint: Optional[str]) -> None:
        self._merge_expected_fingerprint(payload, expected_fingerprint)
        try:
            result = execute_tool(tool_name, payload)
        except PlanConflictError as exc:
            self._write_error(HTTPStatus.PRECONDITION_FAILED, str(exc), current_fingerprint=exc.current_fingerprint)
            return
        except ValueError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:
            self._write_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc), kind="internal_error")
            return
        self._write_json(HTTPStatus.OK, result, extra_headers=self._etag_headers(result.get("fingerprint")))

    def _execute_tool_wrapper(self, tool_name: str, tool_input: Dict[str, Any]) -> None:
        try:
            result = execute_tool(tool_name, tool_input)
        except PlanConflictError as exc:
            self._write_error(HTTPStatus.PRECONDITION_FAILED, str(exc), current_fingerprint=exc.current_fingerprint)
            return
        except ValueError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:
            self._write_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc), kind="internal_error")
            return
        headers = self._etag_headers(result.get("fingerprint"))
        self._write_json(HTTPStatus.OK, {"tool": tool_name, "input": tool_input, "result": result}, extra_headers=headers)

    def _write_json(self, status: HTTPStatus, payload: Dict[str, Any], extra_headers: Optional[Dict[str, str]] = None) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
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
