# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 7.3.2  |  Capítulo 7.3 - A WBS, o modelo classificado
# Seção: Passo 2 - classificar e escrever a tabela

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    o smart location do Capítulo 7.2, em forma compacta,
#    mais o dicionário tecnológico do capítulo
# ============================================================
import os, csv
from Autodesk.Revit.DB import (FilteredElementCollector, Level,
    Element, ElementId, BuiltInCategory, BuiltInParameter,
    LocationPoint, LocationCurve, RevitLinkInstance)

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

PROGETTO = "SNW"                    # WBS_s01: o projeto

# o ramo tecnológico: disciplina (t01) e categoria (t02)
# para cada categoria do Revit. É a tabela do capítulo.
DIZIONARIO = {
    BuiltInCategory.OST_Conduit:             ("ELE", "CND"),
    BuiltInCategory.OST_ConduitFitting:      ("ELE", "CND"),
    BuiltInCategory.OST_CableTray:           ("ELE", "PSS"),
    BuiltInCategory.OST_CableTrayFitting:    ("ELE", "PSS"),
    BuiltInCategory.OST_ElectricalEquipment: ("ELE", "QEL"),
    BuiltInCategory.OST_ElectricalFixtures:  ("ELE", "POW"),
    BuiltInCategory.OST_LightingFixtures:    ("ELE", "LIG"),
    BuiltInCategory.OST_DataDevices:         ("ELE", "NET"),
    BuiltInCategory.OST_FireAlarmDevices:    ("ELE", "SAF"),
    BuiltInCategory.OST_DuctCurves:          ("MEC", "VNT"),
    BuiltInCategory.OST_PipeCurves:          ("MEC", "TUB"),
}

# ---- o smart location do Capítulo 7.2, compactado ----
def punto(el):
    loc = el.Location
    if isinstance(loc, LocationPoint):
        return loc.Point
    if isinstance(loc, LocationCurve):
        return loc.Curve.Evaluate(0.5, True)
    bb = el.get_BoundingBox(None)
    return (bb.Min + bb.Max) / 2.0 if bb else None

livelli = sorted(((Element.Name.GetValue(l), l.Elevation)
                  for l in FilteredElementCollector(doc)
                  .OfClass(Level)), key=lambda c: c[1])

def livello(el, p):
    lid = el.LevelId
    if lid != ElementId.InvalidElementId:
        return Element.Name.GetValue(doc.GetElement(lid))
    if p is None:
        return ""
    scelto = livelli[0][0]
    for nome, quota in livelli:
        if quota <= p.Z + 0.01:
            scelto = nome
    return scelto

# os ambientes do link, com a triagem por caixas do 7.2:
# antes a caixa do ambiente, IsPointInRoom só nos candidatos
gruppi_locali = []
for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
    ldoc = li.GetLinkDocument()
    if ldoc is None:
        continue
    coppie = []
    for s in (FilteredElementCollector(ldoc)
              .OfCategory(BuiltInCategory.OST_Rooms)
              .WhereElementIsNotElementType()):
        bb = s.get_BoundingBox(None)
        if s.Area > 0 and bb is not None:
            coppie.append((s, bb))
    if coppie:
        gruppi_locali.append((li.GetTotalTransform().Inverse, coppie))

def locale(p, gioco=0.5):
    if p is None:
        return None
    for inv, coppie in gruppi_locali:
        q = inv.OfPoint(p)
        for s, bb in coppie:
            if (bb.Min.X - gioco <= q.X <= bb.Max.X + gioco and
                    bb.Min.Y - gioco <= q.Y <= bb.Max.Y + gioco and
                    bb.Min.Z - gioco <= q.Z <= bb.Max.Z + gioco):
                if s.IsPointInRoom(q):
                    return s
    return None

# ============================================================
# 1. DO NOME AO CÓDIGO                                  [ENG]
#    o nível vira L01/L02..., o ambiente R<número>,
#    o exterior EXT: códigos curtos, estáveis, ordenáveis
# ============================================================
def codice_livello(nome):
    cifre = "".join(c for c in nome if c.isdigit())
    if cifre:
        return "L" + cifre.zfill(2)
    return (nome[:3] or "XXX").upper()

def codice_locale(s):
    if s is None:
        return "EXT"
    num = s.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString()
    return "R" + (num or "XXX")

# ============================================================
# 2. A TABELA, UMA LINHA POR ELEMENTO         [REVIT] + [OUT]
#    o CSV é o ponto de encontro: o script propõe,
#    o coordenador revisa no Excel, o Passo 3 aplica
# ============================================================
percorso = os.path.join(os.path.expanduser("~"), "Documents",
                        "wbs_elementi.csv")
righe = []
for bic, (t01, t02) in DIZIONARIO.items():
    for el in (FilteredElementCollector(doc).OfCategory(bic)
               .WhereElementIsNotElementType()):
        p = punto(el)
        s = locale(p)
        righe.append([el.Id.IntegerValue, el.Category.Name,
                      PROGETTO,
                      codice_livello(livello(el, p)),
                      codice_locale(s),
                      t01, t02])

with open(percorso, "w") as f:
    w = csv.writer(f, delimiter=";", lineterminator="\n")
    w.writerow(["Id", "Categoria", "WBS_s01", "WBS_s02",
                "WBS_s03", "WBS_t01", "WBS_t02"])
    w.writerows(righe)

print("Linhas escritas: {} -> {}".format(len(righe), percorso))
esterni = sum(1 for r in righe if r[4] == "EXT")
print("  com ambiente: {}   externos: {}".format(
    len(righe) - esterni, esterni))
for r in righe[:3]:
    print("  {} {} -> {}-{}-{}-{}-{}".format(*r))
