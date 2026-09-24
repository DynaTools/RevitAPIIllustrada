# -*- coding: utf-8 -*-
"""Interruptor que transforma uma sessão de modelagem em material didático."""

__title__ = "Rec\nSessão"
__doc__ = (
    "Grava uma sessão de modelagem para material didático.\n\n"
    "LIGADO: cada comando concluído é registrado automaticamente e uma "
    "captura de tela da janela do Revit é salva na pasta da sessão — "
    "modele normalmente, sem pausas.\n"
    "DESLIGADO: para a gravação, gera um relatório em Markdown (um passo "
    "por comando, com imagem e detalhes) e abre a pasta da sessão.\n\n"
    "As sessões ficam em Documents\\RecSessioni."
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
        prompt=u"Nome da sessão (vira o nome da pasta):",
        title=u"Rec Sessão",
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
            u"Rec Sessão", u"REC LIGADO — {}".format(session_dir))
    except Exception:
        pass


def _stop_recording():
    session_dir = rec.stop_session()
    script.toggle_icon(False)
    if not session_dir or not op.isdir(session_dir):
        forms.alert(u"Nenhuma sessão ativa encontrada.", title=u"Rec Sessão")
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
