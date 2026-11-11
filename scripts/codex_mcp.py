"""Call DiffMind through Codex's native MCP client without restarting the desktop.

Uses only Python's standard library. OAuth credentials stay in Codex's credential
store. No host model turn is started. --check only discovers tools; --query
performs one real MCP search that may consume DiffMind points and requires consent.
"""

import argparse
import json
import queue
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit


class BridgeError(Exception):
    """A sanitized, user-actionable failure; never include raw CLI/RPC errors."""


def read_configuration(codex, server, expected_url):
    """Read configuration through Codex, rejecting other targets/manual credentials."""
    parsed = urlsplit(expected_url)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (not re.fullmatch(r"[A-Za-z0-9_-]+", server)
            or not (parsed.scheme == "https" or parsed.scheme == "http" and local)
            or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != "/mcp/open"):
        raise BridgeError("invalid_target")
    try:
        result = subprocess.run([codex, "mcp", "get", server, "--json"],
                                capture_output=True, text=True, encoding="utf-8", timeout=15)
        if result.returncode:
            raise BridgeError("configuration_unavailable")
        entry = json.loads(result.stdout)
        transport = entry.get("transport", {})
        if (entry.get("enabled") is False or transport.get("type") != "streamable_http"
                or transport.get("url") != expected_url):
            raise BridgeError("configuration_target_mismatch")
        if any(transport.get(key) for key in
               ("http_headers", "env_http_headers", "bearer_token_env_var")):
            raise BridgeError("manual_credentials_not_supported")
        allowed = entry.get("enabled_tools")
        if ((allowed is not None and "diffmind_web_search" not in allowed)
                or "diffmind_web_search" in (entry.get("disabled_tools") or [])):
            raise BridgeError("tool_disabled_by_configuration")
        # Overrides apply only to this ephemeral context, never to config.toml.
        selected = {"url": expected_url, "enabled": True}
        for key in ("enabled_tools", "disabled_tools", "tools", "tool_timeout_sec", "startup_timeout_sec", "oauth"):
            if entry.get(key) is not None:
                selected[key] = entry[key]
        return {"mcp_servers": {server: selected}}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        raise BridgeError("configuration_unavailable") from exc


class NativeClient:
    """A bounded stdio RPC connection; stderr and raw RPC errors are never printed."""

    def __init__(self, codex):
        self.process = subprocess.Popen([codex, "app-server", "--listen", "stdio://"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self.messages = queue.Queue(maxsize=2048)
        self.next_id = 0
        self.interactive_request = False
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                self.messages.put(message)
        finally:
            self.messages.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def request(self, method, params, timeout=45):
        self.next_id += 1
        request_id = self.next_id
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeError("rpc_timeout")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise BridgeError("rpc_timeout") from exc
            if message is None:
                raise BridgeError("native_client_closed")
            if "method" in message and "id" in message:
                # Never auto-approve a host permission request or OAuth elicitation.
                self.interactive_request = True
                self.send({"id": message["id"], "error": {
                    "code": -32601, "message": "Interactive request requires the host UI"}})
                raise BridgeError("host_interaction_required")
            if message.get("id") != request_id or "method" in message:
                continue
            if "error" in message:
                code = message["error"].get("code")
                raise BridgeError("native_api_unavailable" if code == -32601 else "native_rpc_failed")
            return message["result"]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()


def run(codex, server, expected_url, query=None, max_results=None):
    """Discover or call the sole public tool using an ephemeral native MCP context."""
    config = read_configuration(codex, server, expected_url)
    client = NativeClient(codex)
    try:
        client.request("initialize", {"clientInfo": {"name": "diffmind_skill_bridge", "version": "1.0.0"},
                                      "capabilities": {"experimentalApi": True}})
        client.send({"method": "initialized", "params": {}})
        context = client.request("thread/start", {"ephemeral": True, "config": config})
        thread_id = context["thread"]["id"]
        deadline = time.monotonic() + 30
        while True:
            inventory = client.request("mcpServerStatus/list", {"threadId": thread_id,
                "serverName": server, "detail": "toolsAndAuthOnly", "limit": 10})
            entry = next((item for item in inventory.get("data", []) if item.get("name") == server), None)
            status = (entry or {}).get("runtimeStatus")
            if entry and "diffmind_web_search" in entry.get("tools", {}) and status in {"connected", None}:
                break
            if status == "authenticationRequired":
                raise BridgeError("reauthentication_required")
            if status in {"failed", "cancelled", "disabled"} or time.monotonic() >= deadline:
                raise BridgeError("tool_unavailable")
            time.sleep(0.5)
        if query is None:
            return {"ready": True, "server": server, "tool": "diffmind_web_search"}
        arguments = {"query": query}
        if max_results is not None:
            arguments["maxResults"] = max_results
        # One call only. An ambiguous failure must not trigger a second paid search.
        result = client.request("mcpServer/tool/call", {"threadId": thread_id, "server": server,
            "tool": "diffmind_web_search", "arguments": arguments}, timeout=120)
        return {"ready": True, "result": result}
    finally:
        client.close()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--server", default="diffmind-open")
    parser.add_argument("--expected-url", default="https://mcp.diffmind.ai/mcp/open")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="Discover tools only; never run a search")
    action.add_argument("--query", help="Execute the user's authorized search, once")
    parser.add_argument("--max-results", type=int)
    args = parser.parse_args()
    if args.query is not None and not args.query.strip():
        parser.error("--query must not be empty")
    try:
        result = run(args.codex, args.server, args.expected_url, args.query, args.max_results)
        print(json.dumps(result, ensure_ascii=False))
    except (BridgeError, OSError, KeyError, TypeError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, BridgeError) else "native_client_failed"
        print(json.dumps({"ready": False, "reason": reason}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
