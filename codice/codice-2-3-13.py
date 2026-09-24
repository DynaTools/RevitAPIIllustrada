# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 2.3.13  |  Capítulo 2.3 - RevitPythonShell, o playground
# Seção: Juntando tudo no playground

from Autodesk.Revit.DB import *

# doc e uidoc são as chaves já na ignição (nada a definir)
walls = FilteredElementCollector(doc)\
    .OfClass(Wall)\
    .WhereElementIsNotElementType()

total = 0
spessi = 0

for wall in walls:
    total = total + 1
    if wall.Width > 0.2:
        spessi = spessi + 1

print("Paredes no total:", total)
print("Espessas (> 0.2):", spessi)
