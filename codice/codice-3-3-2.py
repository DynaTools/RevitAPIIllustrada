# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.3.2  |  Capítulo 3.3 - O collector a fundo
# Seção: Filtros rápidos e filtros lentos

from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory

# mesmos dutos, duas perguntas diferentes
istanze = (FilteredElementCollector(doc)
           .OfCategory(BuiltInCategory.OST_DuctCurves)
           .WhereElementIsNotElementType())   # as peças colocadas

tipi = (FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_DuctCurves)
        .WhereElementIsElementType())         # as receitas de catálogo

print("dutos colocados   ->", istanze.GetElementCount())
print("tipos de catálogo ->", tipi.GetElementCount())
