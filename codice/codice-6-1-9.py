# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 6.1.9  |  Capítulo 6.1 - As primitivas geométricas
# Seção: O raio - ReferenceIntersector

from Autodesk.Revit.DB import (ReferenceIntersector, XYZ,
    FindReferenceTarget, ElementCategoryFilter, BuiltInCategory)

FT_M = 0.3048

# view3d = uma vista 3D ativa (ex. doc.ActiveView, se for uma View3D)
# Cria o intersector sobre uma vista 3D (obrigatória)
cat_filt    = ElementCategoryFilter(BuiltInCategory.OST_StructuralColumns)
intersector = ReferenceIntersector(cat_filt,
                  FindReferenceTarget.Face, view3d)
intersector.FindReferencesInRevitLinks = False

# Raio vertical para baixo a partir do eixo da EC-01
origin    = XYZ(32.40 / FT_M, 18.20 / FT_M, 8.00 / FT_M)   # a 8 m
direction = XYZ(0, 0, -1)                                      # para baixo

result = intersector.FindNearest(origin, direction)
if result:
    t_m = result.Proximity * FT_M
    print("Primeira superfície atingida a {:.3f} m".format(t_m))
    print("Referência: {}".format(result.GetReference().ElementId))
else:
    print("Nenhuma superfície atingida na direção dada.")
