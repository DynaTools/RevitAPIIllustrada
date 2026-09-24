# -*- coding: utf-8 -*-
"""Furação — os furos passantes dos eletrodutos, do clique à entrega.

Janela (folga, saliência, workset)  ->  clique no link estrutural  ->
os mesmos passos do capítulo (triagem por caixas, segmento dentro do
hospedeiro, cilindro com a folga)  ->  um Generic Model por furo, com Marca
progressiva e Comentários, no workset de colocação. Resumo com ids clicáveis
na janela de output do pyRevit.

Faixas:  [PY] Python puro  [REVIT] Revit API  [ENG] dados e fórmulas  [OUT] console
"""

import os
import math

from pyrevit import revit, script, forms
from pyrevit import DB

from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List

MM_FT = 1 / 304.8

CAT_CONDUIT = [DB.BuiltInCategory.OST_Conduit,
               DB.BuiltInCategory.OST_ConduitFitting]
CAT_OSPITI  = [DB.BuiltInCategory.OST_Walls,
               DB.BuiltInCategory.OST_Floors,
               DB.BuiltInCategory.OST_StructuralFraming]


# ======================================================================
#  1. A JANELA DOS PARÂMETROS ................................... [PY]
# ======================================================================
class FuracaoWindow(forms.WPFWindow):
    """Lê a casca XAML: folga, saliência e workset de colocação."""

    def __init__(self, xaml):
        forms.WPFWindow.__init__(self, xaml)
        self.valori = None                 # None até apertar Furar

    def fora_click(self, sender, args):
        def numero(casella, default):
            try:
                return float(casella.Text.replace(",", "."))
            except ValueError:
                return default
        self.valori = (numero(self.franco, 25.0),
                       numero(self.sporgenza, 25.0),
                       self.workset.Text.strip() or u"FURAÇÃO")
        self.Close()


# ======================================================================
#  2. AS FUNÇÕES DO CAPÍTULO ........................... [ENG] + [REVIT]
#     triagem por caixas, sólido maior, cilindro do furo
# ======================================================================
def scatola_nel_mondo(el, tr):
    bb = el.get_BoundingBox(None)
    if bb is None:
        return None
    xs, ys, zs = [], [], []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                p = tr.OfPoint(DB.XYZ(x, y, z))
                xs.append(p.X); ys.append(p.Y); zs.append(p.Z)
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def si_toccano(a, b, gioco=0.1):
    return (a[0] - gioco <= b[3] and b[0] - gioco <= a[3] and
            a[1] - gioco <= b[4] and b[1] - gioco <= a[4] and
            a[2] - gioco <= b[5] and b[2] - gioco <= a[5])


def solido(el):
    migliore, volume = None, 0.0
    for g in el.get_Geometry(DB.Options()):
        pezzi = (g.GetInstanceGeometry()
                 if isinstance(g, DB.GeometryInstance) else [g])
        for s in pezzi:
            if isinstance(s, DB.Solid) and s.Volume > volume:
                migliore, volume = s, s.Volume
    return migliore


def cilindro(centro, direzione, raggio, lung):
    base   = centro - direzione * (lung / 2.0)
    piano  = DB.Plane.CreateByNormalAndOrigin(direzione, base)
    anello = DB.CurveLoop()
    anello.Append(DB.Arc.Create(piano, raggio, 0.0, math.pi))
    anello.Append(DB.Arc.Create(piano, raggio, math.pi, 2 * math.pi))
    return DB.GeometryCreationUtilities.CreateExtrusionGeometry(
        List[DB.CurveLoop]([anello]), direzione, lung)


# ======================================================================
#  3. O FLUXO .................................. [PY] / [REVIT] / [ENG]
# ======================================================================
doc = revit.doc
uidoc = revit.uidoc
out = script.get_output()

# 3.1  a janela ................................................ [PY]
XAML = os.path.join(os.path.dirname(__file__), "FuracaoWindow.xaml")
finestra = FuracaoWindow(XAML)
finestra.ShowDialog()
if finestra.valori is None:
    script.exit()                          # fechada sem Furar
franco_mm, sporgenza_mm, nome_ws = finestra.valori
franco    = franco_mm * MM_FT
sporgenza = sporgenza_mm * MM_FT

# 3.2  o clique no link estrutural ............................. [REVIT]
try:
    rif = uidoc.Selection.PickObject(ObjectType.Element,
                                     "Selecione o link estrutural")
except OperationCanceledException:
    script.exit()
link = doc.GetElement(rif.ElementId)
if not isinstance(link, DB.RevitLinkInstance):
    forms.alert("O elemento selecionado não é um link do Revit.",
                title="Furação", exitscript=True)
doc_str = link.GetLinkDocument()
trasf   = link.GetTotalTransform()         # mundo do link -> o nosso
inv     = trasf.Inverse

# 3.3  coleta e triagem por caixas ............................. [REVIT]
conduit = []
for cat in CAT_CONDUIT:
    conduit += list(DB.FilteredElementCollector(doc)
                    .OfCategory(cat).WhereElementIsNotElementType())
ospiti = []
for cat in CAT_OSPITI:
    ospiti += list(DB.FilteredElementCollector(doc_str)
                   .OfCategory(cat).WhereElementIsNotElementType())

scatole_ospiti = []
for osp in ospiti:
    b = scatola_nel_mondo(osp, trasf)
    if b:
        scatole_ospiti.append((osp, b))

candidate = []
for imp in conduit:
    bb = imp.get_BoundingBox(None)
    if bb is None:
        continue
    a = (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)
    for osp, b in scatole_ospiti:
        if si_toccano(a, b):
            candidate.append((imp, osp))

# 3.4  o segmento dentro do hospedeiro e a medida .............. [ENG]
opzioni = DB.SolidCurveIntersectionOptions()
opzioni.ResultType = DB.SolidCurveIntersectionMode.CurveSegmentsInside

fori, fermi, muti = [], 0, 0
for imp, osp in candidate:
    loc = imp.Location
    if not hasattr(loc, "Curve"):          # as conexões não têm eixo
        muti += 1
        continue
    curva = loc.Curve.CreateTransformed(inv)
    sol   = solido(osp)
    if sol is None:
        continue
    esito = sol.IntersectWithCurve(curva, opzioni)
    if esito.SegmentCount == 0:
        continue                           # caixas próximas, sem cruzamento
    seg    = esito.GetCurveSegment(0)
    e0, e1 = seg.GetEndPoint(0), seg.GetEndPoint(1)
    fermo = False
    for estremo in (curva.GetEndPoint(0), curva.GetEndPoint(1)):
        if (e0.DistanceTo(estremo) < 0.03 or
                e1.DistanceTo(estremo) < 0.03):
            fermo = True                   # PARA dentro: embutimento
    if fermo:
        fermi += 1
        continue
    p = imp.get_Parameter(
        DB.BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM)
    if p is None or not p.HasValue:
        muti += 1
        continue
    raggio    = p.AsDouble() / 2.0 + franco
    centro    = trasf.OfPoint((e0 + e1) / 2.0)
    direzione = trasf.OfVector(e1 - e0).Normalize()
    lung      = e0.DistanceTo(e1) + 2 * sporgenza
    fori.append((centro, direzione, raggio, lung, imp.Id))

# 3.5  o workset e a colocação em transação ................... [REVIT]
categoria = DB.ElementId(DB.BuiltInCategory.OST_GenericModel)
posati = []

with revit.Transaction("Furação automática"):
    ws_id = None
    if doc.IsWorkshared:
        for ws in (DB.FilteredWorksetCollector(doc)
                   .OfKind(DB.WorksetKind.UserWorkset)):
            if ws.Name == nome_ws:
                ws_id = ws.Id
        if ws_id is None:
            ws_id = DB.Workset.Create(doc, nome_ws).Id
    n = 0
    for centro, direzione, raggio, lung, id_imp in fori:
        n += 1
        D = raggio * 2 / MM_FT
        L = lung / MM_FT
        ds = DB.DirectShape.CreateElement(doc, categoria)
        ds.SetShape(List[DB.GeometryObject](
            [cilindro(centro, direzione, raggio, lung)]))
        ds.SetName("Furo passante D{:.0f}".format(D))
        ds.get_Parameter(
            DB.BuiltInParameter.ALL_MODEL_MARK).Set("F{:03d}".format(n))
        ds.get_Parameter(
            DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(
            "Furo passante D{:.0f} L{:.0f} - eletroduto {}".format(
                D, L, id_imp))
        if ws_id is not None:
            ds.get_Parameter(
                DB.BuiltInParameter.ELEM_PARTITION_PARAM).Set(
                ws_id.IntegerValue)
        posati.append((ds.Id, D, L))

# 3.6  o resumo com ids clicáveis .............................. [OUT]
out.print_md("# Furação &mdash; {0} furos".format(len(posati)))
out.print_md("Link: **{0}** &middot; candidatos {1} &middot; "
             "embutimentos {2} &middot; sem eixo ou diâmetro {3}"
             .format(doc_str.Title, len(candidate), fermi, muti))
out.print_md("Folga **{0:.0f} mm** &middot; saliência **{1:.0f} mm** "
             "&middot; workset **{2}**".format(
                 franco_mm, sporgenza_mm,
                 nome_ws if doc.IsWorkshared else "(não compartilhado)"))
for eid, D, L in posati[:10]:
    out.print_md("- {0}  D **{1:.0f}** mm, L **{2:.0f}** mm"
                 .format(out.linkify(eid), D, L))
if len(posati) > 10:
    out.print_md("- ... e mais {0}".format(len(posati) - 10))
