# -*- coding: utf-8 -*-
"""Startup da extensão pyRevit: registra a API Routes `revit-mcp`.

Expõe uma pequena ponte HTTP DENTRO do Revit, para que um processo externo
(o CLI do Claude Code, por meio de um servidor MCP) possa comandar o modelo vivo.

Arquitetura:
    CLI do Claude Code  --MCP(stdio)-->  revit_mcp_server.py  --HTTP-->  (aqui)

Endpoints (caminho base /revit-mcp/, porta padrão 48884):
    GET  /revit-mcp/status       -> saúde + documento ativo
    GET  /revit-mcp/model-info   -> documento, vista ativa, seleção atual
    POST /revit-mcp/execute      -> roda código da API do Revit no modelo vivo
                                    corpo: {"code": "...", "description": "..."}

IMPORTANTE
----------
* Este arquivo roda no engine IronPython de startup do pyRevit, e todo handler
  de rota que declara `doc`/`uidoc`/`uiapp` é despachado para a thread PRINCIPAL
  do Revit por meio de um ExternalEvent (veja pyrevit.routes.server.handler). É
  isso que torna seguro abrir uma `Transaction` de dentro de um handler.
* Mantenha este módulo compatível com IronPython 2.7: nada de f-strings, use
  ``.format()``, e ``exec(code, ns)`` (válido tanto em Py2 quanto em Py3).
* O servidor Routes precisa estar habilitado nas configurações do pyRevit
  (pyRevit_config.ini -> [routes] enabled = true) e o Revit recarregado.

Autor: Paulo Giavoni
"""
from __future__ import print_function

import json
import traceback

from pyrevit import routes


# ---------------------------------------------------------------------------
# Definição da API
# ---------------------------------------------------------------------------
api = routes.API('revit-mcp')


def _coerce(value):
    """Devolve uma versão de ``value`` serializável em JSON (dentro do possível)."""
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
    """Substituto mínimo de stdout/stderr (evita as manias de unicode do StringIO)."""
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
    """Sonda de vida sem contexto. NÃO declara uiapp/uidoc/doc, então roda na
    thread do servidor HTTP (NÃO pelo ExternalEvent da thread principal) e
    responde na hora. O painel a usa para descobrir a porta sem travar a
    própria thread principal contra um handler que precisa do contexto Revit."""
    return {'status': 'active', 'server': 'revit-mcp'}


# ---------------------------------------------------------------------------
# GET /revit-mcp/status
# ---------------------------------------------------------------------------
@api.route('/status', methods=['GET'])
def rmcp_status(uiapp):
    """Verificação de saúde leve. Roda na thread principal do Revit."""
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
    """Devolve o documento, a vista ativa e um resumo da seleção atual."""
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
    """Executa código da API do Revit no modelo vivo.

    Corpo (application/json):
        {"code": "<código python>", "description": "<opcional>"}

    O código roda na thread principal do Revit com estes nomes disponíveis:
        __revit__, uiapp, uidoc, doc, DB, UI, clr, json
    Atribua uma variável chamada ``OUT`` para devolver um valor a quem chamou.
    Envolva toda modificação do modelo em uma DB.Transaction.
    """
    import sys

    body = request.data if request is not None else None
    if not isinstance(body, dict):
        return routes.Response(
            status=400,
            data={'ok': False, 'error': 'o corpo da requisição deve ser um objeto JSON'})

    code = body.get('code')
    if not code:
        return routes.Response(
            status=400,
            data={'ok': False, 'error': 'falta "code" no corpo da requisição'})

    # nomes disponíveis para o código executado
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
        exec(code, namespace)  # noqa: S102 - intencional, ponte local confiável
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
