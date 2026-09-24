# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 6.1.6  |  Capítulo 6.1 - As primitivas geométricas
# Seção: O bounding box alinhado (AABB) - BoundingBoxXYZ

from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.DB import (Outline, BoundingBoxIntersectsFilter,
    FilteredElementCollector, BuiltInCategory)

FT_M = 0.3048

ref = uidoc.Selection.PickObject(ObjectType.Element)
element = doc.GetElement(ref.ElementId)   # clique na EC-01
# AABB do elemento selecionado
bb = element.get_BoundingBox(None)
d  = bb.Max - bb.Min                     # vetor dimensões (em pés)
C  = bb.Min + d * 0.5                    # centro
V  = d.X * d.Y * d.Z * (FT_M ** 3)     # volume em m^3

print("Min: ({:.2f}, {:.2f}, {:.2f}) m".format(
    bb.Min.X*FT_M, bb.Min.Y*FT_M, bb.Min.Z*FT_M))
print("Max: ({:.2f}, {:.2f}, {:.2f}) m".format(
    bb.Max.X*FT_M, bb.Max.Y*FT_M, bb.Max.Z*FT_M))
print("Volume AABB: {:.2f} m^3   Volume OBB real: 0.36 m^3".format(V))

# Clash detection com estruturas: elementos que cruzam este AABB
outline  = Outline(bb.Min, bb.Max)
bb_filt  = BoundingBoxIntersectsFilter(outline)
clash = (FilteredElementCollector(doc)
         .OfCategory(BuiltInCategory.OST_StructuralFraming)
         .WherePasses(bb_filt)
         .ToElements())
print("Estruturas no AABB: {}".format(len(clash)))
