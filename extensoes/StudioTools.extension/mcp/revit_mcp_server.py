#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor MCP (Model Context Protocol) mínimo, via stdio, que faz a ponte com o Revit.

CLI do Claude Code  --MCP stdio (JSON-RPC)-->  ESTE  --HTTP-->  pyRevit Routes

Zero dependências de terceiros: só a biblioteca padrão do Python 3, então roda
em qualquer Python 3 sem `pip install`. O Claude Code o inicia como
subprocesso (veja a configuração MCP escrita pelo botão ClaudeChat).

A URL do Routes do Revit de destino vem da variável de ambiente
REVIT_MCP_URL, por exemplo "http://127.0.0.1:48884/revit-mcp" (padrão abaixo).

Os diagnósticos vão só para STDERR. STDOUT é reservado ao protocolo JSON-RPC.
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

# stdout é o canal do protocolo -> força UTF-8, quebras de linha LF e flush.
try:
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass


def log(*args):
    """Escreve uma linha de diagnóstico em stderr (nunca em stdout)."""
    try:
        sys.stderr.write("[revit-mcp] " + " ".join(str(a) for a in args) + "\n")
        sys.stderr.flush()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Ponte HTTP para o pyRevit Routes
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
        # O Routes devolve corpos JSON úteis mesmo em 4xx/5xx (ex.: tracebacks)
        raw = ex.read().decode("utf-8", "replace")
    except urllib.error.URLError as ex:
        raise RuntimeError(
            "Não foi possível alcançar o Revit em {0} ({1}). O Revit está "
            "aberto, com o Routes do pyRevit habilitado?".format(url, ex))
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw}


# ---------------------------------------------------------------------------
# Implementação dos tools
# ---------------------------------------------------------------------------
def tool_revit_execute(args):
    code = args.get("code")
    if not code:
        return True, "Erro: o argumento 'code' é obrigatório."
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
            "Executa código Python (API do Revit) no modelo Revit VIVO e "
            "devolve a sua saída. O código roda na thread principal do Revit "
            "com estes nomes já disponíveis: doc (Document), uidoc "
            "(UIDocument), uiapp (UIApplication), DB (Autodesk.Revit.DB), UI "
            "(Autodesk.Revit.UI), clr, json. O runtime é IronPython 2.7 — "
            "escreva código compatível com IronPython 2 (use .format(), não "
            "f-strings). Para DEVOLVER dados, atribua-os a uma variável "
            "chamada OUT (precisa ser serializável em JSON: "
            "str/num/bool/list/dict). Tudo o que você imprimir com print() "
            "também é capturado. SEMPRE envolva as modificações do modelo em "
            "uma transação, por exemplo:\n"
            "    t = DB.Transaction(doc, 'minha alteração')\n"
            "    t.Start()\n"
            "    # ... modificar ...\n"
            "    t.Commit()\n"
            "Prefira DB.FilteredElementCollector para as consultas. Os "
            "comprimentos estão em unidades internas (pés); converta com "
            "DB.UnitUtils.ConvertToInternalUnits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Código IronPython 2.7 (API do Revit) a executar.",
                },
                "description": {
                    "type": "string",
                    "description": "Descrição curta e legível da intenção.",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "revit_status",
        "description": "Verificação de saúde da ponte com o Revit; devolve o "
                       "título do documento ativo, se houver um modelo aberto.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "revit_model_info",
        "description": "Devolve o documento ativo, a vista ativa e a seleção "
                       "atual (ids, nomes e categorias dos elementos).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_FUNCS = {
    "revit_execute": tool_revit_execute,
    "revit_status": tool_revit_status,
    "revit_model_info": tool_revit_model_info,
}


# ---------------------------------------------------------------------------
# Encanamento JSON-RPC
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
        return  # notificação, sem resposta

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
            is_error, text = True, "O tool '{0}' falhou: {1}".format(name, ex)
        reply(req_id, {
            "content": [{"type": "text", "text": text}],
            "isError": bool(is_error),
        })
        return

    # Método desconhecido: erro para requisições, ignora as notificações
    if is_request:
        reply_error(req_id, -32601, "Method not found: {0}".format(method))


def main():
    log("iniciado; ponte para", BASE_URL)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except Exception as ex:
            log("JSON inválido:", ex)
            continue
        try:
            handle(message)
        except Exception as ex:
            log("erro no handler:", ex)
            rid = message.get("id") if isinstance(message, dict) else None
            if rid is not None:
                reply_error(rid, -32603, "Internal error: {0}".format(ex))
    log("stdin fechado; saindo")


if __name__ == "__main__":
    main()
