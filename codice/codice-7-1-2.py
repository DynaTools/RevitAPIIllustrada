# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 7.1.2  |  Capítulo 7.1 - A furação automática
# Seção: Passo 2 - o furo com folga, no workset dedicado

# ============================================================
# 0. RETOMADA                                            [PY]
#    mesma sessão RPS do Passo 1: doc, trasf, candidate
#    e solido() ainda estão na memória
# ============================================================
import math
from Autodesk.Revit.DB import (SolidCurveIntersectionOptions,
    SolidCurveIntersectionMode, BuiltInParameter, Transaction,
    DirectShape, ElementId, BuiltInCategory, CurveLoop, Arc,
    Plane, GeometryCreationUtilities, GeometryObject,
    FilteredWorksetCollector, WorksetKind, Workset)
from System.Collections.Generic import List

MM_FT     = 1 / 304.8
FRANCO    = 25.0 * MM_FT          # folga radial, por lado
SPORGENZA = 25.0 * MM_FT          # além das duas faces, por lado
NOME_WS   = "FURAÇÃO"

# ============================================================
# 1. O SEGMENTO DENTRO DO HOSPEDEIRO           [ENG] + [REVIT]
#    o eixo do eletroduto cortado pelo sólido estrutural: dali
#    vêm o centro, a direção e o comprimento do furo
# ============================================================
opzioni = SolidCurveIntersectionOptions()
opzioni.ResultType = SolidCurveIntersectionMode.CurveSegmentsInside
inv = trasf.Inverse               # o nosso mundo -> o do link

fori, fermi, muti = [], 0, 0
for imp, osp in candidate:
    loc = imp.Location
    if not hasattr(loc, "Curve"):     # as conexões não têm eixo
        muti += 1
        continue
    curva = loc.Curve.CreateTransformed(inv)
    sol   = solido(osp)
    if sol is None:
        continue
    esito = sol.IntersectWithCurve(curva, opzioni)
    if esito.SegmentCount == 0:
        continue                      # caixas próximas, sem cruzamento
    seg    = esito.GetCurveSegment(0)
    e0, e1 = seg.GetEndPoint(0), seg.GetEndPoint(1)
    # o eletroduto que PARA dentro do hospedeiro não é passante
    fermo = False
    for estremo in (curva.GetEndPoint(0), curva.GetEndPoint(1)):
        if (e0.DistanceTo(estremo) < 0.03 or
                e1.DistanceTo(estremo) < 0.03):
            fermo = True
    if fermo:
        fermi += 1
        continue
    p = imp.get_Parameter(
        BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM)
    if p is None or not p.HasValue:
        muti += 1
        continue
    raggio    = p.AsDouble() / 2.0 + FRANCO
    centro    = trasf.OfPoint((e0 + e1) / 2.0)   # no nosso mundo
    direzione = trasf.OfVector(e1 - e0).Normalize()
    lung      = e0.DistanceTo(e1) + 2 * SPORGENZA
    fori.append((centro, direzione, raggio, lung, imp.Id))

# ============================================================
# 2. O CILINDRO DO FURO                                  [ENG]
#    um círculo no plano perpendicular à direção,
#    extrudado por toda a espessura mais as sobras
# ============================================================
def cilindro(centro, direzione, raggio, lung):
    base   = centro - direzione * (lung / 2.0)
    piano  = Plane.CreateByNormalAndOrigin(direzione, base)
    anello = CurveLoop()
    anello.Append(Arc.Create(piano, raggio, 0.0, math.pi))
    anello.Append(Arc.Create(piano, raggio, math.pi, 2 * math.pi))
    return GeometryCreationUtilities.CreateExtrusionGeometry(
        List[CurveLoop]([anello]), direzione, lung)

# ============================================================
# 3. O WORKSET E A COLOCAÇÃO                   [REVIT] + [OUT]
#    o workset FURAÇÃO é procurado, e se falta nasce aqui;
#    cada furo é atribuído a ele pelo parâmetro de partição
# ============================================================
categoria = ElementId(BuiltInCategory.OST_Mass)

t = Transaction(doc, "Furação com folga")
t.Start()

ws_id = None
if doc.IsWorkshared:
    for ws in (FilteredWorksetCollector(doc)
               .OfKind(WorksetKind.UserWorkset)):
        if ws.Name == NOME_WS:
            ws_id = ws.Id
    if ws_id is None:
        ws_id = Workset.Create(doc, NOME_WS).Id

for centro, direzione, raggio, lung, id_imp in fori:
    ds = DirectShape.CreateElement(doc, categoria)
    ds.SetShape(List[GeometryObject](
        [cilindro(centro, direzione, raggio, lung)]))
    ds.SetName("Furo D{:.0f} eletroduto {}".format(
        raggio * 2 / MM_FT, id_imp))
    if ws_id is not None:
        ds.get_Parameter(
            BuiltInParameter.ELEM_PARTITION_PARAM).Set(
            ws_id.IntegerValue)
t.Commit()

print("Furos colocados: {}".format(len(fori)))
print("  param dentro (embutimentos): {}".format(fermi))
print("  sem eixo ou sem diâmetro: {}".format(muti))
if ws_id is not None:
    print("Workset de colocação: {}".format(NOME_WS))
else:
    print("ATENÇÃO: modelo não compartilhado, sem workset.")
