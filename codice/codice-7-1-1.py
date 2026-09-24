# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 7.1.1  |  Capítulo 7.1 - A furação automática
# Seção: Passo 1 - o clash exato, sem folga

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    bibliotecas, documento ativo e seleção
# ============================================================
from Autodesk.Revit.DB import (FilteredElementCollector,
    BuiltInCategory, RevitLinkInstance, Options, Solid,
    GeometryInstance, SolidUtils, BooleanOperationsUtils,
    BooleanOperationsType, DirectShape, ElementId, Transaction,
    XYZ, GeometryObject)
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# ============================================================
# 1. O LINK, ESCOLHIDO COM O MOUSE                     [REVIT]
#    desta vez quem indica o link é o usuário, não o collector
# ============================================================
rif  = uidoc.Selection.PickObject(ObjectType.Element,
                                  "Selecione o link estrutural")
link = doc.GetElement(rif.ElementId)
if not isinstance(link, RevitLinkInstance):
    raise SystemExit("Isso não é um link do Revit.")

doc_str = link.GetLinkDocument()      # o documento do link
trasf   = link.GetTotalTransform()    # mundo do link -> o nosso

# ============================================================
# 2. OS ELETRODUTOS AQUI, AS ESTRUTURAS DO LINK        [REVIT]
#    todas as categorias de eletroduto, trechos E conexões
# ============================================================
CAT_CONDUIT = [BuiltInCategory.OST_Conduit,
               BuiltInCategory.OST_ConduitFitting]
conduit = []
for cat in CAT_CONDUIT:
    conduit += list(FilteredElementCollector(doc)
                    .OfCategory(cat).WhereElementIsNotElementType())

CAT_OSPITI = [BuiltInCategory.OST_Walls,
              BuiltInCategory.OST_Floors,
              BuiltInCategory.OST_StructuralFraming]
ospiti = []
for cat in CAT_OSPITI:
    ospiti += list(FilteredElementCollector(doc_str)
                   .OfCategory(cat).WhereElementIsNotElementType())

# ============================================================
# 3. A TRIAGEM POR CAIXAS (Parte 6)                      [ENG]
#    o booleano é caro: antes se descartam os pares
#    distantes, quase de graça
# ============================================================
def scatola_nel_mondo(el, tr):
    bb = el.get_BoundingBox(None)
    if bb is None:
        return None
    xs, ys, zs = [], [], []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                p = tr.OfPoint(XYZ(x, y, z))
                xs.append(p.X); ys.append(p.Y); zs.append(p.Z)
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

def si_toccano(a, b, gioco=0.1):
    return (a[0] - gioco <= b[3] and b[0] - gioco <= a[3] and
            a[1] - gioco <= b[4] and b[1] - gioco <= a[4] and
            a[2] - gioco <= b[5] and b[2] - gioco <= a[5])

scatole_ospiti = []
for osp in ospiti:
    b = scatola_nel_mondo(osp, trasf)   # do link para o nosso mundo
    if b:
        scatole_ospiti.append((osp, b))

candidate = []
for imp in conduit:
    bb = imp.get_BoundingBox(None)      # já no nosso mundo
    if bb is None:
        continue
    a = (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)
    for osp, b in scatole_ospiti:
        if si_toccano(a, b):
            candidate.append((imp, osp))

# ============================================================
# 4. O CLASH EXATO, SEM FOLGA                  [ENG] + [REVIT]
#    a interseção booleana dos dois sólidos: o volume real
#    do conflito, com a direção real do elemento
# ============================================================
def solido(el):
    migliore, volume = None, 0.0
    for g in el.get_Geometry(Options()):
        pezzi = (g.GetInstanceGeometry()
                 if isinstance(g, GeometryInstance) else [g])
        for s in pezzi:
            if isinstance(s, Solid) and s.Volume > volume:
                migliore, volume = s, s.Volume
    return migliore

clash = []
for imp, osp in candidate:
    s_imp = solido(imp)                 # já no nosso mundo
    s_osp = solido(osp)
    if s_imp is None or s_osp is None:
        continue
    s_osp = SolidUtils.CreateTransformed(s_osp, trasf)
    try:
        inters = BooleanOperationsUtils.ExecuteBooleanOperation(
            s_imp, s_osp, BooleanOperationsType.Intersect)
    except Exception:
        continue                      # geometrias hostis ao booleano
    if inters and inters.Volume > 1e-9:
        clash.append((imp.Id, osp.Id, inters))

# ============================================================
# 5. AS MASSAS EM TRANSAÇÃO                    [REVIT] + [OUT]
# ============================================================
categoria = ElementId(BuiltInCategory.OST_Mass)
CM3_FT3   = 28316.8                   # pés cúbicos -> cm cúbicos

t = Transaction(doc, "Clash de eletrodutos, sem folga")
t.Start()
for id_imp, id_osp, s in clash:
    ds = DirectShape.CreateElement(doc, categoria)
    ds.SetShape(List[GeometryObject]([s]))
    ds.SetName("Clash conduit {} vs {}".format(id_imp, id_osp))
t.Commit()

print("Eletrodutos no modelo ativo: {}".format(len(conduit)))
print("Hospedeiros no link {}: {}".format(doc_str.Title, len(ospiti)))
print("Candidatos após a triagem: {}".format(len(candidate)))
print("Massas de clash colocadas: {}".format(len(clash)))
for id_imp, id_osp, s in clash[:3]:
    print("  eletroduto {} vs {}: {:.1f} cm3"
          .format(id_imp, id_osp, s.Volume * CM3_FT3))
