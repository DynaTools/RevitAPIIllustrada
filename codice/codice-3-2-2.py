# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.2.2  |  Capítulo 3.2 - O primeiro script
# Seção: A pergunta que se faz ao modelo

n = (
    FilteredElementCollector(doc)            # R4 - construtor sem new
    .OfCategory(BuiltInCategory.OST_Walls)   # R2 + R6
    .WhereElementIsNotElementType()          # LEI III - só instâncias
    .GetElementCount()                       # R2 - método, com ( )
)
print(n)
