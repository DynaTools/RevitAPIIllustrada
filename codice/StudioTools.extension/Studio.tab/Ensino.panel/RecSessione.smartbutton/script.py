# -*- coding: utf-8 -*-
"""Toggle recorder that turns a modeling session into teaching material."""

__title__ = "Rec\nSessione"
__doc__ = (
    "Records a modeling session for teaching material.\n\n"
    "ON: every finished command is logged automatically and a screenshot "
    "of the Revit window is saved in the session folder — model normally, "
    "no pausing needed.\n"
    "OFF: stops recording, generates a Markdown report (one step per "
    "command, with image and details) and opens the session folder.\n\n"
    "Sessions are saved in Documents\\RecSessioni."
)
__author__ = "Paulo Giavoni"

import os
import os.path as op

from pyrevit import HOST_APP, forms, revit, script

import recsessione as rec


def __selfinit__(script_cmp, ui_button_cmp, __rvt__):
    return True


def _start_recording():
    doc = revit.doc
    default_name = u""
    try:
        default_name = op.splitext(doc.Title)[0]
    except Exception:
        pass
    nome = forms.ask_for_string(
        default=default_name,
        prompt="Nome della sessione (diventa il nome della cartella):",
        title="Rec Sessione",
    )
    if not nome:
        return
    session_dir = rec.start_session(
        nome,
        documento=doc.Title if doc else u"",
        revit=getattr(HOST_APP, "pretty_name", None) or HOST_APP.version,
    )
    script.toggle_icon(True)
    try:
        forms.show_balloon(
            "Rec Sessione", u"REC ON — {}".format(session_dir))
    except Exception:
        pass


def _stop_recording():
    session_dir = rec.stop_session()
    script.toggle_icon(False)
    if not session_dir or not op.isdir(session_dir):
        forms.alert("Nessuna sessione attiva trovata.", title="Rec Sessione")
        return
    rec.generate_readme(session_dir)
    try:
        os.startfile(session_dir)
    except Exception:
        pass


if __name__ == "__main__":
    if rec.is_active():
        _stop_recording()
    else:
        _start_recording()
