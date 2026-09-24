# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 2.3.10  |  Capítulo 2.3 - RevitPythonShell, o playground
# Seção: Repetir com o for, a esteira transportadora

from Autodesk.Revit.DB import *
walls = FilteredElementCollector(doc).OfClass(Wall)\
    .WhereElementIsNotElementType()   # a coleção

for wall in walls:
    print(wall.Name)
