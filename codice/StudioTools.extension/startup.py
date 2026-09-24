# -*- coding: utf-8 -*-
"""pyRevit extension startup: registers the `revit-mcp` Routes API.

This exposes a tiny HTTP bridge INSIDE Revit so that an external process
(the Claude Code CLI, via an MCP server) can drive the live model.

Architecture:
    Claude Code CLI  --MCP(stdio)-->  revit_mcp_server.py  --HTTP-->  (here)

Endpoints (base path /revit-mcp/, default port 48884):
    GET  /revit-mcp/status       -> health + active document
    GET  /revit-mcp/model-info   -> document, active view, current selection
    POST /revit-mcp/execute      -> run Revit API code on the live model
                                    body: {"code": "...", "description": "..."}

IMPORTANT
---------
* This file runs under pyRevit's IronPython startup engine, and every route
  handler that declares `doc`/`uidoc`/`uiapp` is dispatched onto Revit's MAIN
  thread through an ExternalEvent (see pyrevit.routes.server.handler). That is
  what makes it safe to open a `Transaction` from inside a handler.
* Keep this module IronPython-2.7 compatible: no f-strings, use ``.format()``,
  and ``exec(code, ns)`` (valid in both Py2 and Py3).
* The Routes server must be enabled in pyRevit settings
  (pyRevit_config.ini -> [routes] enabled = true) and Revit reloaded.

Author: Paulo Giavoni
"""
from __future__ import print_function

import json
import traceback

from pyrevit import routes


# ---------------------------------------------------------------------------
# API definition
# ---------------------------------------------------------------------------
api = routes.API('revit-mcp')


def _coerce(value):
    """Return a JSON-serializable version of ``value`` (best effort)."""
    if value is None:
        return None
    try:
        json.dumps(value)
        return value
    except Exception:
        try:
            return str(value)
        except Exception:
            return repr(value)


class _Capture(object):
    """Minimal stdout/stderr replacement (avoids StringIO unicode quirks)."""
    def __init__(self):
        self._parts = []

    def write(self, text):
        try:
            self._parts.append(text)
        except Exception:
            self._parts.append(str(text))

    def flush(self):
        pass

    def getvalue(self):
        out = []
        for part in self._parts:
            if isinstance(part, bytes):
                try:
                    part = part.decode('utf-8', 'replace')
                except Exception:
                    part = str(part)
            elif not isinstance(part, str):
                part = str(part)
            out.append(part)
        return ''.join(out)


# ---------------------------------------------------------------------------
# GET /revit-mcp/ping
# ---------------------------------------------------------------------------
@api.route('/ping', methods=['GET'])
def rmcp_ping():
    """Context-free liveness probe. Declares NO uiapp/uidoc/doc, so it runs on
    the HTTP server thread (NOT through the main-thread ExternalEvent) and
    answers instantly. The panel uses this to discover the port without
    dead-locking its own main thread against a Revit-context handler."""
    return {'status': 'active', 'server': 'revit-mcp'}


# ---------------------------------------------------------------------------
# GET /revit-mcp/status
# ---------------------------------------------------------------------------
@api.route('/status', methods=['GET'])
def rmcp_status(uiapp):
    """Lightweight health check. Runs on Revit's main thread."""
    title = None
    try:
        uidoc = getattr(uiapp, 'ActiveUIDocument', None)
        if uidoc is not None:
            doc = getattr(uidoc, 'Document', None)
            if doc is not None:
                title = doc.Title
    except Exception:
        pass
    return {
        'status': 'active',
        'health': 'healthy',
        'revit_available': True,
        'server': 'revit-mcp',
        'document': title,
    }


# ---------------------------------------------------------------------------
# GET /revit-mcp/model-info
# ---------------------------------------------------------------------------
@api.route('/model-info', methods=['GET'])
def rmcp_model_info(uiapp, uidoc, doc):
    """Return document, active view and current selection summary."""
    info = {'document': None, 'active_view': None, 'selection': []}
    if doc is None:
        return info

    try:
        info['document'] = {
            'title': doc.Title,
            'path': doc.PathName,
            'is_workshared': bool(doc.IsWorkshared),
        }
    except Exception:
        pass

    try:
        view = doc.ActiveView
        if view is not None:
            info['active_view'] = {
                'name': view.Name,
                'type': str(view.ViewType),
            }
    except Exception:
        pass

    try:
        sel_ids = uidoc.Selection.GetElementIds()
        sel = []
        for eid in sel_ids:
            el = doc.GetElement(eid)
            if el is None:
                continue
            try:
                eid_val = eid.Value
            except AttributeError:
                eid_val = eid.IntegerValue
            cat = el.Category
            sel.append({
                'id': eid_val,
                'name': getattr(el, 'Name', None),
                'category': cat.Name if cat is not None else None,
            })
        info['selection'] = sel
        info['selection_count'] = len(sel)
    except Exception:
        pass

    return info


# ---------------------------------------------------------------------------
# POST /revit-mcp/execute
# ---------------------------------------------------------------------------
@api.route('/execute', methods=['POST'])
def rmcp_execute(request, uiapp, uidoc, doc):
    """Execute Revit API code against the live model.

    Body (application/json):
        {"code": "<python source>", "description": "<optional>"}

    The code runs on Revit's main thread with these names in scope:
        __revit__, uiapp, uidoc, doc, DB, UI, clr, json
    Set a variable named ``OUT`` to return a value to the caller.
    Wrap any model modification in a DB.Transaction.
    """
    import sys

    body = request.data if request is not None else None
    if not isinstance(body, dict):
        return routes.Response(
            status=400,
            data={'ok': False, 'error': 'request body must be a JSON object'})

    code = body.get('code')
    if not code:
        return routes.Response(
            status=400,
            data={'ok': False, 'error': 'missing "code" in request body'})

    # names available to the executed code
    import clr  # noqa: F401
    from pyrevit.api import DB, UI

    namespace = {
        '__revit__': uiapp,
        'uiapp': uiapp,
        'uidoc': uidoc,
        'doc': doc,
        'DB': DB,
        'UI': UI,
        'clr': clr,
        'json': json,
        'OUT': None,
    }

    cap = _Capture()
    old_out, old_err = sys.stdout, sys.stderr
    result = {'ok': True, 'stdout': '', 'result': None}

    sys.stdout = cap
    sys.stderr = cap
    try:
        exec(code, namespace)  # noqa: S102 - intentional, local trusted bridge
        result['result'] = _coerce(namespace.get('OUT', None))
    except Exception as ex:
        result['ok'] = False
        result['error'] = '{0}: {1}'.format(type(ex).__name__, ex)
        result['traceback'] = traceback.format_exc()
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
        result['stdout'] = cap.getvalue()

    status = routes.OK if result['ok'] else routes.INTERNAL_SERVER_ERROR
    return routes.Response(status=status, data=result)
