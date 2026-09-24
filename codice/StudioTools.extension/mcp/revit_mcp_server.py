#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal MCP (Model Context Protocol) stdio server that bridges to Revit.

Claude Code CLI  --MCP stdio (JSON-RPC)-->  THIS  --HTTP-->  pyRevit Routes

Zero third-party dependencies: only the Python 3 standard library, so it runs
under any Python 3 without `pip install`. Claude Code launches it as a
subprocess (see the MCP config written by the ClaudeChat pushbutton).

The target Revit Routes URL is taken from the REVIT_MCP_URL environment
variable, e.g. "http://127.0.0.1:48884/revit-mcp" (default below).

Diagnostics go to STDERR only. STDOUT is reserved for the JSON-RPC protocol.
"""
import json
import os
import sys
import urllib.request
import urllib.error

DEFAULT_URL = "http://127.0.0.1:48884/revit-mcp"
BASE_URL = (os.environ.get("REVIT_MCP_URL") or DEFAULT_URL).rstrip("/")

SERVER_NAME = "revit"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL = "2024-11-05"

# stdout is the protocol channel -> force UTF-8, LF newlines, and flushing.
try:
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass


def log(*args):
    """Write a diagnostic line to stderr (never stdout)."""
    try:
        sys.stderr.write("[revit-mcp] " + " ".join(str(a) for a in args) + "\n")
        sys.stderr.flush()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# HTTP bridge to pyRevit Routes
# ---------------------------------------------------------------------------
def _http(method, path, payload=None, timeout=300):
    url = BASE_URL + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        # Routes returns useful JSON bodies even on 4xx/5xx (e.g. tracebacks)
        raw = ex.read().decode("utf-8", "replace")
    except urllib.error.URLError as ex:
        raise RuntimeError(
            "Cannot reach Revit at {0} ({1}). Is Revit open with pyRevit "
            "Routes enabled?".format(url, ex))
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def tool_revit_execute(args):
    code = args.get("code")
    if not code:
        return True, "Error: 'code' argument is required."
    result = _http("POST", "/execute",
                   {"code": code, "description": args.get("description", "")})
    is_error = not bool(result.get("ok", True))
    return is_error, json.dumps(result, indent=2, ensure_ascii=False)


def tool_revit_status(_args):
    result = _http("GET", "/status", timeout=30)
    return False, json.dumps(result, indent=2, ensure_ascii=False)


def tool_revit_model_info(_args):
    result = _http("GET", "/model-info", timeout=60)
    return False, json.dumps(result, indent=2, ensure_ascii=False)


TOOLS = [
    {
        "name": "revit_execute",
        "description": (
            "Execute Python (Revit API) code against the LIVE Revit model and "
            "return its output. The code runs on Revit's main thread with "
            "these names already in scope: doc (Document), uidoc "
            "(UIDocument), uiapp (UIApplication), DB (Autodesk.Revit.DB), UI "
            "(Autodesk.Revit.UI), clr, json. Runtime is IronPython 2.7 — write "
            "IronPython-2 compatible code (use .format(), not f-strings). To "
            "RETURN data, assign it to a variable named OUT (must be JSON-"
            "serializable: str/num/bool/list/dict). Anything you print() is "
            "captured too. ALWAYS wrap model modifications in a transaction, "
            "e.g.:\n"
            "    t = DB.Transaction(doc, 'my change')\n"
            "    t.Start()\n"
            "    # ... modify ...\n"
            "    t.Commit()\n"
            "Prefer DB.FilteredElementCollector for queries. Lengths are in "
            "internal units (feet); convert with "
            "DB.UnitUtils.ConvertToInternalUnits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "IronPython 2.7 Revit API source to run.",
                },
                "description": {
                    "type": "string",
                    "description": "Short human-readable description of intent.",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "revit_status",
        "description": "Health check for the Revit bridge; returns the active "
                       "document title if a model is open.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "revit_model_info",
        "description": "Return the active document, active view and the current "
                       "selection (element ids, names, categories).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_FUNCS = {
    "revit_execute": tool_revit_execute,
    "revit_status": tool_revit_status,
    "revit_model_info": tool_revit_model_info,
}


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------
def send(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def reply(req_id, result):
    send({"jsonrpc": "2.0", "id": req_id, "result": result})


def reply_error(req_id, code, message):
    send({"jsonrpc": "2.0", "id": req_id,
          "error": {"code": code, "message": message}})


def handle(message):
    method = message.get("method")
    req_id = message.get("id")
    is_request = req_id is not None

    if method == "initialize":
        params = message.get("params") or {}
        protocol = params.get("protocolVersion") or DEFAULT_PROTOCOL
        reply(req_id, {
            "protocolVersion": protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
        return

    if method in ("notifications/initialized", "initialized"):
        return  # notification, no reply

    if method == "ping":
        if is_request:
            reply(req_id, {})
        return

    if method == "tools/list":
        reply(req_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        func = TOOL_FUNCS.get(name)
        if func is None:
            reply_error(req_id, -32602, "Unknown tool: {0}".format(name))
            return
        try:
            is_error, text = func(args)
        except Exception as ex:
            is_error, text = True, "Tool '{0}' failed: {1}".format(name, ex)
        reply(req_id, {
            "content": [{"type": "text", "text": text}],
            "isError": bool(is_error),
        })
        return

    # Unknown method: error for requests, ignore for notifications
    if is_request:
        reply_error(req_id, -32601, "Method not found: {0}".format(method))


def main():
    log("started; bridging to", BASE_URL)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except Exception as ex:
            log("bad JSON:", ex)
            continue
        try:
            handle(message)
        except Exception as ex:
            log("handler error:", ex)
            rid = message.get("id") if isinstance(message, dict) else None
            if rid is not None:
                reply_error(rid, -32603, "Internal error: {0}".format(ex))
    log("stdin closed; exiting")


if __name__ == "__main__":
    main()
