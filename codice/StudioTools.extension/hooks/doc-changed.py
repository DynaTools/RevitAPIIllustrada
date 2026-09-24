# -*- coding: utf-8 -*-
"""Extension hook: runs after every committed transaction (app-wide).

When Rec Sessione is ON, logs one step per transaction and schedules a
screenshot on a background thread. Exits immediately when OFF.

NOTE: requires the classic Python loader (new_loader = false in the
pyRevit config) — the pyRevit 6.x C# loader never registers extension
hooks, so this script silently does not run under it.
"""

import os.path as op
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


def _category_counts(rec, doc, element_ids):
    counts = {}
    for eid in list(element_ids)[:rec.MAX_ELEMENTS_PER_STEP]:
        name = None
        try:
            el = doc.GetElement(eid)
            if el is not None:
                if el.Category is not None:
                    name = el.Category.Name
                else:
                    name = el.GetType().Name
        except Exception:
            name = None
        name = name or u"Altro"
        counts[name] = counts.get(name, 0) + 1
    return counts


def _active_view_name(doc):
    try:
        view = doc.ActiveView
        return view.Name if view is not None else None
    except Exception:
        return None


def _main(rec, session_dir):
    from pyrevit import EXEC_PARAMS

    args = EXEC_PARAMS.event_args
    doc = args.GetDocument()

    names = [n.replace(u"&", u"") for n in args.GetTransactionNames() if n]
    nome = u" + ".join(names) if names else u"(senza nome)"
    if nome in rec.IGNORED_TRANSACTIONS:
        return

    operation = str(args.Operation)
    if "RolledBack" in operation:
        return
    if operation == "TransactionUndone":
        rec.annotate_last(session_dir, u"Annullato con Ctrl+Z: {}".format(nome))
        return
    if operation == "TransactionRedone":
        rec.annotate_last(session_dir, u"Ripristinato con Ctrl+Y: {}".format(nome))
        return

    record = {
        "t": time.time(),
        "ora": time.strftime("%H:%M:%S"),
        "nome": nome,
        "documento": doc.Title,
        "vista": _active_view_name(doc),
        "aggiunti": _category_counts(rec, doc, args.GetAddedElementIds()),
        "modificati": _category_counts(rec, doc, args.GetModifiedElementIds()),
        "eliminati": len(list(args.GetDeletedElementIds())),
    }
    png_path = rec.record_step(session_dir, record)
    rec.capture_screen_async(png_path)


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
