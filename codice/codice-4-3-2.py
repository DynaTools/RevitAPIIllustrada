# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.3.2  |  Capítulo 4.3 - Parâmetros em bloco
# Seção: Escrever com critério, o filtro no meio

    liv = doc.GetElement(el.LevelId)      # None se o elemento não tem nível
    if liv and liv.Name == "P02":
