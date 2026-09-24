# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.3.1  |  Capítulo 3.3 - O collector a fundo
# Seção: As quatro entradas do fichário

from Autodesk.Revit.DB import FilteredElementCollector

# 1. o arquivo inteiro
tutto = FilteredElementCollector(doc)

# 2. os elementos que o Revit pode iterar na vista ativa
vista = FilteredElementCollector(doc, doc.ActiveView.Id)

# 3. só um maço de fichas que você já tem na mão
scelti = FilteredElementCollector(doc, uidoc.Selection.GetElementIds())

print("arquivo inteiro  ->", tutto.GetElementCount())
print("na vista         ->", vista.GetElementCount())
print("na seleção       ->", scelti.GetElementCount())
