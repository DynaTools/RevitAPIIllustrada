# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 3.3.3  |  Capítulo 3.3 - O collector a fundo
# Seção: Filtros rápidos e filtros lentos

from Autodesk.Revit.DB import (FilteredElementCollector, Wall,
                               ElementLevelFilter)

# o nível vem emprestado da planta ativa, depois as duas malhas
liv = doc.ActiveView.GenLevel        # None fora das plantas
muri_liv = (FilteredElementCollector(doc)
            .OfClass(Wall)                            # rápido
            .WherePasses(ElementLevelFilter(liv.Id))  # rápido também
            .ToElements())
print("Paredes associadas a {}: {}".format(liv.Name, len(muri_liv)))
