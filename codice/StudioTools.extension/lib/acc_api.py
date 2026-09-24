# -*- coding: utf-8 -*-
"""Autodesk Platform Services (APS / Forge) helper for ACC Data Management.

Pure standard-library implementation (no external packages) so it runs under
the pyRevit CPython engine. It provides:

  * 3-legged OAuth (PKCE, public client - no client secret needed),
  * a tiny local HTTP server to catch the OAuth redirect,
  * token caching / refresh in %APPDATA%,
  * Data Management traversal (hubs, projects, folders, items),
  * helpers to turn an ACC item lineage URN into the GUID bytes Revit needs
    to build a cloud ModelPath.

The cloud ModelPath itself must be built on the Revit side (it needs the Revit
API), using `lineage_urn_to_guid_bytes()` + the project GUID.
"""

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser

try:
    # Python 3 (pyRevit CPython engine)
    import urllib.request as _urlreq
    import urllib.parse as _urlparse
    from urllib.error import HTTPError, URLError
    from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:  # pragma: no cover - IronPython fallback
    raise

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
AUTH_BASE = "https://developer.api.autodesk.com/authentication/v2"
DM_BASE = "https://developer.api.autodesk.com"

DEFAULT_SCOPES = "data:read account:read"

_TOKEN_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"),
                          "pyRevit_ACC")
_TOKEN_FILE = os.path.join(_TOKEN_DIR, "token.json")


# ----------------------------------------------------------------------------
# Low-level HTTP
# ----------------------------------------------------------------------------
def _get_json(url, token):
    req = _urlreq.Request(url, method="GET")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/json")
    try:
        resp = _urlreq.urlopen(req, timeout=60)
        return json.loads(resp.read().decode("utf-8"))
    except HTTPError as ex:
        body = ex.read().decode("utf-8", "replace")
        raise RuntimeError("GET %s -> HTTP %s: %s" % (url, ex.code, body))
    except URLError as ex:
        raise RuntimeError("GET %s -> %s" % (url, ex))


def _post_form(url, data):
    body = _urlparse.urlencode(data).encode("utf-8")
    req = _urlreq.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        resp = _urlreq.urlopen(req, timeout=60)
        return json.loads(resp.read().decode("utf-8"))
    except HTTPError as ex:
        body = ex.read().decode("utf-8", "replace")
        raise RuntimeError("POST %s -> HTTP %s: %s" % (url, ex.code, body))
    except URLError as ex:
        raise RuntimeError("POST %s -> %s" % (url, ex))


# ----------------------------------------------------------------------------
# Token cache
# ----------------------------------------------------------------------------
def _load_cache():
    try:
        with open(_TOKEN_FILE, "r") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_cache(data):
    try:
        if not os.path.isdir(_TOKEN_DIR):
            os.makedirs(_TOKEN_DIR)
        with open(_TOKEN_FILE, "w") as fh:
            json.dump(data, fh)
    except Exception:
        pass


def clear_cache():
    try:
        os.remove(_TOKEN_FILE)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# PKCE helpers
# ----------------------------------------------------------------------------
def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=")
    verifier = verifier.decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _RedirectHandler(BaseHTTPRequestHandler):
    captured = {}

    def do_GET(self):  # noqa: N802 (stdlib naming)
        parsed = _urlparse.urlparse(self.path)
        qs = _urlparse.parse_qs(parsed.query)
        _RedirectHandler.captured = {k: v[0] for k, v in qs.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = ("<html><body style='font-family:Segoe UI;text-align:center;"
               "margin-top:60px'><h2>Autenticacao concluida.</h2>"
               "<p>Pode fechar esta aba e voltar ao Revit.</p></body></html>")
        self.wfile.write(msg.encode("utf-8"))

    def log_message(self, *args):  # silence
        return


def _run_redirect_server(host, port, timeout):
    server = HTTPServer((host, port), _RedirectHandler)
    server.timeout = timeout
    _RedirectHandler.captured = {}

    def _serve():
        # Handle a single request (the redirect), then stop.
        server.handle_request()

    t = threading.Thread(target=_serve)
    t.daemon = True
    t.start()
    return server, t


# ----------------------------------------------------------------------------
# OAuth 3-legged (PKCE, public client)
# ----------------------------------------------------------------------------
def _exchange_code(client_id, code, verifier, redirect_uri):
    return _post_form(AUTH_BASE + "/token", {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
    })


def _refresh(client_id, refresh_token, scopes):
    return _post_form(AUTH_BASE + "/token", {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "scope": scopes,
    })


def _store_token(client_id, tok):
    now = int(time.time())
    cache = _load_cache()
    cache[client_id] = {
        "access_token": tok.get("access_token"),
        "refresh_token": tok.get("refresh_token"),
        "expires_at": now + int(tok.get("expires_in", 3600)) - 60,
        "scope": tok.get("scope", DEFAULT_SCOPES),
    }
    _save_cache(cache)
    return cache[client_id]


def login_interactive(client_id, redirect_uri, scopes=DEFAULT_SCOPES,
                      timeout=180):
    """Run the full 3-legged PKCE flow and return an access token string."""
    parsed = _urlparse.urlparse(redirect_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8080

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    server, thread = _run_redirect_server(host, port, timeout)

    auth_url = AUTH_BASE + "/authorize?" + _urlparse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
    })

    webbrowser.open(auth_url)
    thread.join(timeout)

    captured = dict(_RedirectHandler.captured)
    try:
        server.server_close()
    except Exception:
        pass

    if not captured:
        raise RuntimeError("Tempo esgotado esperando o login no navegador.")
    if captured.get("error"):
        raise RuntimeError("Erro de autorizacao: %s - %s"
                           % (captured.get("error"),
                              captured.get("error_description", "")))
    if captured.get("state") != state:
        raise RuntimeError("State invalido (possivel CSRF). Tente novamente.")

    code = captured.get("code")
    if not code:
        raise RuntimeError("Nenhum 'code' retornado pelo Autodesk.")

    tok = _exchange_code(client_id, code, verifier, redirect_uri)
    rec = _store_token(client_id, tok)
    return rec["access_token"]


def get_access_token(client_id, redirect_uri, scopes=DEFAULT_SCOPES):
    """Return a valid access token, refreshing or logging in as needed."""
    cache = _load_cache().get(client_id, {})
    now = int(time.time())

    if cache.get("access_token") and cache.get("expires_at", 0) > now:
        return cache["access_token"]

    if cache.get("refresh_token"):
        try:
            tok = _refresh(client_id, cache["refresh_token"], scopes)
            return _store_token(client_id, tok)["access_token"]
        except Exception:
            pass  # fall through to interactive

    return login_interactive(client_id, redirect_uri, scopes)


# ----------------------------------------------------------------------------
# Data Management traversal
# ----------------------------------------------------------------------------
def _get_all(url, token):
    """GET following JSON:API pagination, returning (data[], included[])."""
    data = []
    included = []
    while url:
        payload = _get_json(url, token)
        data.extend(payload.get("data", []))
        included.extend(payload.get("included", []))
        url = (payload.get("links", {}) or {}).get("next", {})
        url = url.get("href") if isinstance(url, dict) else None
    return data, included


def list_hubs(token):
    data, _ = _get_all(DM_BASE + "/project/v1/hubs", token)
    return [{"id": h["id"], "name": h["attributes"]["name"]} for h in data]


def list_projects(token, hub_id):
    url = DM_BASE + "/project/v1/hubs/%s/projects" % hub_id
    data, _ = _get_all(url, token)
    return [{"id": p["id"], "name": p["attributes"]["name"]} for p in data]


def list_top_folders(token, hub_id, project_id):
    url = (DM_BASE + "/project/v1/hubs/%s/projects/%s/topFolders"
           % (hub_id, project_id))
    data, _ = _get_all(url, token)
    return [{"id": f["id"], "name": f["attributes"].get("displayName")
             or f["attributes"].get("name")} for f in data]


def list_folder_contents(token, project_id, folder_id):
    """Return (subfolders, items). Items carry the tip version display name."""
    url = (DM_BASE + "/data/v1/projects/%s/folders/%s/contents"
           % (project_id, folder_id))
    data, _included = _get_all(url, token)

    subfolders = []
    items = []
    for d in data:
        dtype = d.get("type")
        attrs = d.get("attributes", {})
        if dtype == "folders":
            subfolders.append({
                "id": d["id"],
                "name": attrs.get("displayName") or attrs.get("name"),
            })
        elif dtype == "items":
            items.append({
                "id": d["id"],
                "name": attrs.get("displayName") or attrs.get("name"),
            })
    return subfolders, items


def build_name_index(token, project_id, root_folder_id, progress=None,
                     max_folders=5000):
    """Recursively index every item under a folder.

    Returns {lower_name: [item_id, ...]} so duplicate names can be detected.
    `progress` is an optional callable(count, current_folder_name).
    """
    index = {}
    stack = [(root_folder_id, "")]
    visited = 0
    while stack and visited < max_folders:
        folder_id, _label = stack.pop()
        visited += 1
        try:
            subs, items = list_folder_contents(token, project_id, folder_id)
        except Exception:
            continue
        for it in items:
            key = (it["name"] or "").strip().lower()
            if key:
                index.setdefault(key, []).append(it["id"])
        for sub in subs:
            stack.append((sub["id"], sub["name"]))
        if progress:
            progress(visited, len(index))
    return index


# ----------------------------------------------------------------------------
# URN -> GUID bytes (for Revit ConvertCloudGUIDsToCloudPath)
# ----------------------------------------------------------------------------
def lineage_urn_to_guid_bytes(item_id):
    """Decode an ACC item lineage URN to the 16 GUID bytes Revit expects.

    Example item_id: 'urn:adsk.wipprod:dm.lineage:AbCdEf...'
    The trailing segment is URL-safe base64 of the 16-byte model GUID, in the
    .NET System.Guid byte order, so it can be fed directly to System.Guid(bytes).
    """
    seg = item_id.split(":")[-1]
    # base64url, restore padding
    seg += "=" * (-len(seg) % 4)
    raw = base64.urlsafe_b64decode(seg)
    if len(raw) != 16:
        raise ValueError("URN nao decodifica para 16 bytes: %s" % item_id)
    return raw


def project_id_to_guid_str(project_id):
    """ACC project id 'b.<guid>' -> '<guid>' for Revit ConvertCloudGUIDs."""
    return project_id[2:] if project_id.startswith("b.") else project_id
