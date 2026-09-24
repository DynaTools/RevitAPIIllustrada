# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.3.6  |  Capítulo 3.3 - O collector a fundo
# Seção: A sequência mental

# primeiro os filtros do Revit...
equip = (FilteredElementCollector(doc)
         .OfCategory(BuiltInCategory.OST_MechanicalEquipment)  # universo
         .WhereElementIsNotElementType()                       # instâncias
         .ToElements())                                        # coleta

# ...depois o Python, só no resíduo
uta = [e for e in equip if "UTA" in e.Symbol.Family.Name]
print("unidades de tratamento de ar ->", len(uta))
