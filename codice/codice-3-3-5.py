# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.3.5  |  Capítulo 3.3 - O collector a fundo
# Seção: Combinar os filtros

from System.Collections.Generic import List
from Autodesk.Revit.DB import (FilteredElementCollector,
                               BuiltInCategory,
                               ElementMulticategoryFilter)

# dutos, tubulações e eletrocalhas de uma vez só
categorie = List[BuiltInCategory]([BuiltInCategory.OST_DuctCurves,
                                   BuiltInCategory.OST_PipeCurves,
                                   BuiltInCategory.OST_CableTray])

rete_mep = (FilteredElementCollector(doc)
            .WherePasses(ElementMulticategoryFilter(categorie))
            .WhereElementIsNotElementType()
            .ToElements())
