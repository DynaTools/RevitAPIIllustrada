# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.3.4  |  Capítulo 4.3 - Parâmetros em bloco
# Seção: Escrever com critério, o filtro no meio

    state = el.LookupParameter("Status").AsString()
    if state == "A verificar":
        el.LookupParameter("Comentários").Set("Pendente")
