# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 5.1.3  |  Capítulo 5.1 - pyRevit, botões e distribuição
# Seção: O pyRevit no lugar do RPS

from pyrevit import revit, script
from Autodesk.Revit.DB import FilteredElementCollector, Wall

doc = revit.doc                      # o mesmo doc do RPS
out = script.get_output()            # a janela pyRevit Output

muri = list(FilteredElementCollector(doc).OfClass(Wall)
            .WhereElementIsNotElementType())

out.print_md("**Paredes no modelo** -- {} instâncias".format(len(muri)))

piu_lungo = max(muri, key=lambda m: m.Location.Curve.Length)
out.print_md("A mais longa -- {}".format(out.linkify(piu_lungo.Id)))
