# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.3.4  |  Capítulo 3.3 - O collector a fundo
# Seção: O filtro por parâmetro, peça por peça

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter,
    ElementId, ParameterValueProvider, FilterStringRule,
    FilterStringEquals, ElementParameterFilter)

# 1. qual coluna do fichário (o parâmetro Mark)
p_id = ElementId(BuiltInParameter.ALL_MODEL_MARK)
# 2. quem vai lê-la, elemento por elemento
fornitore = ParameterValueProvider(p_id)
# 3. a regra da comparação
regola = FilterStringRule(fornitore, FilterStringEquals(), "MEP-001")
# 4. a regra vira um filtro
filtro = ElementParameterFilter(regola)

trovati = (FilteredElementCollector(doc)
           .OfCategory(BuiltInCategory.OST_MechanicalEquipment)
           .WhereElementIsNotElementType()   # rápidos, primeiro
           .WherePasses(filtro)              # lento, por último
           .ToElements())

print("encontrados ->", len(trovati))
for e in trovati:
    print(e.Name)
