# -*- coding: utf-8 -*-
"""Hook da extensão: roda quando uma janela do Revit vai abrir (em todo o app).

Quando o Rec Sessão está LIGADO, grava um passo para a janela (Tipos de
família, editores de parâmetros etc.) e faz uma captura de tela depois de
uma espera longa o bastante para a janela aparecer. Sai na hora quando
está DESLIGADO.

Exige o loader Python clássico (new_loader = false) no pyRevit
6.1-6.3 — a mesma restrição do doc-changed.py.
"""

import os.path as op
import re
import sys
import time
import traceback

# log de erros de reserva, para falhas antes de a pasta da sessão ser conhecida
_DBG_PATH = op.join(op.expanduser("~"), "Documents", "RecSessioni",
                    "hook-debug.log")


def _log_failure(message):
    try:
        f = open(_DBG_PATH, "a")
        f.write("[{}] {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"),
                                   message))
        f.close()
    except Exception:
        pass


def _dialog_info(args):
    """Devolve (dialog_id, mensagem). As TaskDialogs muitas vezes não têm
    id, mas trazem o texto do aviso em Message."""
    dlg_id = None
    try:
        dlg_id = args.DialogId
    except Exception:
        pass
    messaggio = None
    try:
        messaggio = args.Message
        if messaggio:
            messaggio = u" ".join(u"{}".format(messaggio).split())[:160]
    except Exception:
        pass
    if not dlg_id:
        dlg_id = "TaskDialog" if messaggio else "Dialog"
    return dlg_id, messaggio


def _prettify(dlg_id):
    name = re.sub(r"^(TaskDialog_|Dialog_Revit_|Dialog_)", "", dlg_id)
    name = name.replace("_", " ").strip()
    return name or dlg_id


def _main(rec, session_dir):
    from pyrevit import EXEC_PARAMS, HOST_APP

    args = EXEC_PARAMS.event_args
    dlg_id, messaggio = _dialog_info(args)
    if dlg_id in rec.IGNORED_DIALOGS:
        return

    doc_title = None
    try:
        doc_title = HOST_APP.doc.Title if HOST_APP.doc else None
    except Exception:
        pass

    nome = (u"Janela: Aviso" if dlg_id == "TaskDialog"
            else u"Janela: {}".format(_prettify(dlg_id)))
    record = {
        "t": time.time(),
        "ora": time.strftime("%H:%M:%S"),
        "tipo": "finestra",
        "nome": nome,
        "dialog_id": dlg_id,
        "documento": doc_title,
        "aggiunti": {},
        "modificati": {},
        "eliminati": 0,
    }
    if messaggio:
        record["messaggio"] = messaggio
    png_path = rec.record_step(session_dir, record)
    rec.capture_screen_async(png_path, delay_ms=rec.DIALOG_CAPTURE_DELAY_MS)


try:
    _LIB = op.join(op.dirname(op.dirname(op.abspath(__file__))), "lib")
    if _LIB not in sys.path:
        sys.path.append(_LIB)

    import recsessione as rec

    if rec.is_active():
        _session_dir = rec.get_session_dir()
        if _session_dir and op.isdir(_session_dir):
            try:
                _main(rec, _session_dir)
            except Exception:
                # nunca quebrar a modelagem por causa do gravador
                rec.log_error(_session_dir, traceback.format_exc())
except Exception:
    _log_failure(traceback.format_exc())
