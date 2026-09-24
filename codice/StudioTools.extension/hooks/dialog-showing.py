# -*- coding: utf-8 -*-
"""Extension hook: runs when a Revit dialog is about to show (app-wide).

When Rec Sessione is ON, records a step for the dialog (Family Types,
parameter editors, etc.) and captures a screenshot after a delay long
enough for the window to render. Exits immediately when OFF.

Requires the classic Python loader (new_loader = false) on pyRevit
6.1-6.3 — same constraint as doc-changed.py.
"""

import os.path as op
import re
import sys
import time
import traceback

# fallback error log, for failures before the session folder is known
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
    """Return (dialog_id, message). TaskDialogs often have no id, but
    carry the warning text in Message."""
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

    nome = (u"Finestra: Avviso" if dlg_id == "TaskDialog"
            else u"Finestra: {}".format(_prettify(dlg_id)))
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
                # never break modeling because of the recorder
                rec.log_error(_session_dir, traceback.format_exc())
except Exception:
    _log_failure(traceback.format_exc())
