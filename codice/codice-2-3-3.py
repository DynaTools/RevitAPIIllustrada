# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 2.3.3  |  Capítulo 2.3 - RevitPythonShell, o playground
# Seção: A lanterna chamada print

from Autodesk.Revit.DB import *
wall = FilteredElementCollector(doc).OfClass(Wall)\
    .WhereElementIsNotElementType().FirstElement()

print("cheguei até aqui")    # texto: marcar
print(doc.Title)             # valor: ler
print(wall)                  # objeto: e agora?
