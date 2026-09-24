# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.4.4  |  Capítulo 8.4 - Distribuir com o esquema L-2L
# Seção: A ferramenta de obra, do clique à malha

# ============================================================
# 0. AS FERRAMENTAS                                      [PY]
#    também as duas janelas prontas: InputBox e TaskDialog
# ============================================================
FT_M = 0.3048
import math
import clr
clr.AddReference("Microsoft.VisualBasic")
from Microsoft.VisualBasic import Interaction
from Autodesk.Revit.DB import (XYZ, UV, Transform, RevitLinkInstance,
                               Transaction, ElementId, BuiltInParameter)
from Autodesk.Revit.DB.Structure import StructuralType
from Autodesk.Revit.UI import (TaskDialog, TaskDialogCommonButtons,
                               TaskDialogResult)
from Autodesk.Revit.UI.Selection import ObjectType

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# ============================================================
# 1. A LUMINÁRIA-MODELO                                [REVIT]
#    tipo, nível e ORIGEM da família; a origem deve ser
#    o centro do painel, e a ferramenta avisa
# ============================================================
r1  = uidoc.Selection.PickObject(ObjectType.Element,
                                 "Clique na luminária-modelo")
lum = doc.GetElement(r1.ElementId)
bb  = lum.get_BoundingBox(None)
print("Luminária: {} | {}".format(lum.Symbol.Family.Name, lum.Name))
print("Ocupação em planta: {:.2f} x {:.2f} m".format(
    (bb.Max.X - bb.Min.X) * FT_M, (bb.Max.Y - bb.Min.Y) * FT_M))

scarto = (bb.Min + bb.Max) / 2.0 - lum.Location.Point
sx = abs(scarto.X) * FT_M * 1000
sy = abs(scarto.Y) * FT_M * 1000
if max(sx, sy) > 50:
    print("ATENÇÃO: origem fora do centro ({:.0f} x {:.0f} mm);".format(sx, sy))
    print("  corrija a família (Define origem nos planos centrais).")
else:
    print("Origem da família no centro (desvio {:.0f} x {:.0f} mm).".format(sx, sy))

lid = lum.LevelId
if lid == ElementId.InvalidElementId:          # não hospedada: Schedule Level
    lid = lum.get_Parameter(
        BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM).AsElementId()
livello = doc.GetElement(lid)

# ============================================================
# 2. A FACE DO FORRO                            [REVIT]+[ENG]
#    o contorno VERDADEIRO (EdgeLoops), não o bbox UV; se a
#    face mora num vínculo, a sua Transform traz tudo para
#    as coordenadas do modelo hospedeiro
# ============================================================
r2   = uidoc.Selection.PickObject(ObjectType.Face,
          "Clique na face do forro")
host = doc.GetElement(r2.ElementId)
trasf, dove = Transform.Identity, "no modelo"
if isinstance(host, RevitLinkInstance):
    trasf = host.GetTotalTransform()
    dove  = "num vínculo ({})".format(host.Name)
faccia = host.GetGeometryObjectFromReference(r2)
print("Face {} | tipo {}".format(dove, type(faccia).__name__))

anello, per_max = None, 0.0
for k in range(faccia.EdgeLoops.Size):
    loop = faccia.EdgeLoops.get_Item(k)
    per  = sum(e.AsCurve().Length for e in loop)
    if per > per_max:
        anello, per_max = loop, per
vertici = []
for e in anello:
    p = trasf.OfPoint(e.AsCurve().GetEndPoint(0))
    if not vertici or (p - vertici[-1]).GetLength() > 0.001:
        vertici.append(p)

A  = vertici[0]
eU = (vertici[1] - A).Normalize()
eV = trasf.OfVector(faccia.ComputeNormal(UV(0.5, 0.5))).CrossProduct(eU)
us = [(p - A).DotProduct(eU) for p in vertici]
vs = [(p - A).DotProduct(eV) for p in vertici]
u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
O  = A + eU * u0 + eV * v0
lu, lv = (u1 - u0) * FT_M, (v1 - v0) * FT_M
print("Forro: {:.2f} x {:.2f} m | cota z {:.3f} m".format(
    lu, lv, O.Z * FT_M))
print("Nível de lançamento: {}".format(livello.Name))

# ============================================================
# 3. QUANTAS, E EM QUANTAS COLUNAS                       [PY]
#    total e colunas se digitam na janelinha; o arredondamento
#    para cima decide as fileiras, e a última pode ficar incompleta
# ============================================================
N = int(Interaction.InputBox(
    "Quantas luminárias no total? Por exemplo 10", "Malha L-2L", "10"))
C = int(Interaction.InputBox(
    "Em quantas colunas? Por exemplo 3", "Malha L-2L", "3"))

R = int(math.ceil(N / float(C)))
righe, resto = [], N
for j in range(R):
    righe.append(min(C, resto))
    resto -= righe[-1]
print("{} luminárias em {} colunas -> {} fileiras ({})".format(
    N, C, R, "+".join(str(x) for x in righe)))

# ============================================================
# 4. A MALHA L-2L                                       [ENG]
#    cada fileira distribui as SUAS luminárias a meio passo;
#    a fileira incompleta centraliza sozinha o que lhe resta
# ============================================================
print("Passo {:.2f} x {:.2f} m | borda {:.2f} x {:.2f} m".format(
    lu / C, lv / R, lu / C / 2, lv / R / 2))
posizioni = []
for j, quante in enumerate(righe):
    for i in range(quante):
        posizioni.append(O + eU * (u1 - u0) * (i + 0.5) / quante
                           + eV * (v1 - v0) * (j + 0.5) / R)
for k, p in enumerate(posizioni, 1):
    print("  #{:>2}: x={:.3f}  y={:.3f}  z={:.3f} m".format(
        k, p.X * FT_M, p.Y * FT_M, p.Z * FT_M))

# ============================================================
# 5. A CONFIRMAÇÃO E O LANÇAMENTO                     [REVIT]
# ============================================================
esito = TaskDialog.Show("Malha L-2L",
    "Lançar {} luminárias ({} fileiras, {})?".format(
        N, R, "+".join(str(x) for x in righe)),
    TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No)

if esito == TaskDialogResult.Yes:
    t = Transaction(doc, "Malha L-2L de luminárias")
    t.Start()
    if not lum.Symbol.IsActive:
        lum.Symbol.Activate()
    for p in posizioni:
        doc.Create.NewFamilyInstance(p, lum.Symbol, livello,
                                     StructuralType.NonStructural)
    t.Commit()
    print("{} luminárias lançadas no nível {}.".format(
        len(posizioni), livello.Name))
else:
    print("Só análise, nenhum lançamento.")
