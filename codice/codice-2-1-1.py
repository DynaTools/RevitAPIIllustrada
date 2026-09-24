# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 2.1.1  |  Capítulo 2.1 - A Pedra de Roseta
# Seção: Decifrar de ponta a ponta

walls = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Walls)\
    .WhereElementIsNotElementType()         # Lei III - só instâncias

for wall in walls:                          # Regra 7 - for direto
    p = wall.LookupParameter("Comentários") # Regra 2 - método ( )
    print(wall.Name, p.AsString())          # Regra 1 - propriedade
