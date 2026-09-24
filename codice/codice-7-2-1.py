# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 7.2.1  |  Capítulo 7.2 - Onde está cada elemento
# Seção: Passos 1--2 - o ponto e o nível

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    alguns elementos escolhidos com o mouse, para ver o método
# ============================================================
from Autodesk.Revit.DB import (FilteredElementCollector, Level,
    Element, ElementId, BuiltInParameter, LocationPoint,
    LocationCurve)
from Autodesk.Revit.UI.Selection import ObjectType

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
FT_MM = 304.8

# ============================================================
# 1. O PONTO DO ELEMENTO                        [ENG] + [REVIT]
#    todo elemento tem UM ponto que o representa: a inserção,
#    a metade do percurso, ou o centro da sua caixa
# ============================================================
def punto(el):
    loc = el.Location
    if isinstance(loc, LocationPoint):
        return loc.Point, "inserção"
    if isinstance(loc, LocationCurve):
        return loc.Curve.Evaluate(0.5, True), "meio do percurso"
    bb = el.get_BoundingBox(None)
    if bb is not None:
        return (bb.Min + bb.Max) / 2.0, "centro da caixa"
    return None, "sem geometria"

# ============================================================
# 2. O NÍVEL, DOIS CAMINHOS                            [REVIT]
#    primeiro a palavra do elemento (o nível declarado);
#    se falta, a cota do ponto contra os níveis do modelo
# ============================================================
def livello_dichiarato(el):
    lid = el.LevelId
    if lid != ElementId.InvalidElementId:
        return Element.Name.GetValue(doc.GetElement(lid))
    for bip in (BuiltInParameter.SCHEDULE_LEVEL_PARAM,
                BuiltInParameter.RBS_START_LEVEL_PARAM):
        p = el.get_Parameter(bip)
        if p and p.HasValue:
            v = p.AsValueString()
            if v:
                return v
    return ""

livelli = sorted(((Element.Name.GetValue(l), l.Elevation)
                  for l in FilteredElementCollector(doc)
                  .OfClass(Level)), key=lambda c: c[1])

def livello_dalla_quota(z):
    scelto = livelli[0][0]          # abaixo do primeiro: o primeiro
    for nome, quota in livelli:
        if quota <= z + 0.01:
            scelto = nome
    return scelto

# ============================================================
# 3. O TESTE EM ALGUNS ELEMENTOS                        [OUT]
# ============================================================
print("Níveis do modelo:")
for nome, quota in livelli:
    print("  {:<12} cota {:>8.0f} mm".format(nome, quota * FT_MM))

print("")
print(">> Vá para o Revit: clique 3-4 elementos no modelo,")
print(">> depois aperte CONCLUIR na barra de opções.")
riff = uidoc.Selection.PickObjects(ObjectType.Element,
    "Clique os elementos, depois CONCLUIR na barra de opções")
for rif in riff:
    el = doc.GetElement(rif.ElementId)
    p, come = punto(el)
    dich = livello_dichiarato(el)
    dalz = livello_dalla_quota(p.Z) if p else "?"
    print("{} {} ({})".format(el.Id, el.Category.Name, come))
    print("   declarado: {:<12} pela cota: {}".format(
        dich or "-", dalz))
