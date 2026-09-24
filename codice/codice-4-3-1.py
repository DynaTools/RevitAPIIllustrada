# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.3.1  |  Capítulo 4.3 - Parâmetros em bloco
# Seção: Escrever com critério, o filtro no meio

t = Transaction(doc, "Escrever com critério")
t.Start()
for el in targets:
    if <criterio>:                # DECIDIR: só quem passa muda
        el.LookupParameter("...").Set(value)
t.Commit()
