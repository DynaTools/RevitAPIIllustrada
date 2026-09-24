# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 2.3.11  |  Capítulo 2.3 - RevitPythonShell, o playground
# Seção: Repetir com o for, a esteira transportadora

from Autodesk.Revit.DB import *
walls = FilteredElementCollector(doc).OfClass(Wall)\
    .WhereElementIsNotElementType()

total = 0
for wall in walls:
    total = total + 1   # +1 a cada volta
print(total)            # FORA do for: só no final
