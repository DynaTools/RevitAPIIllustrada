# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.6.1  |  Capítulo 8.6 - A cobertura Wi-Fi
# Seção: Passo 1 - o sinal, do probe à antena

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    um ponto para cada coisa, como no smart location
# ============================================================
import math
from Autodesk.Revit.DB import (FilteredElementCollector, Options,
    GeometryInstance, Solid, Line, BuiltInCategory,
    RevitLinkInstance, LocationPoint,
    SolidCurveIntersectionOptions, SolidCurveIntersectionMode)
from Autodesk.Revit.UI.Selection import ObjectType

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

def punto(el):
    loc = el.Location
    if isinstance(loc, LocationPoint):
        return loc.Point
    bb = el.get_BoundingBox(None)
    return (bb.Min + bb.Max) / 2.0 if bb else None

# ============================================================
# 1. O CADERNO DE RÁDIO                                  [ENG]
#    potência, frequência, limiares e pedágios são valores,
#    não algoritmo: calibram-se aqui, não no código
# ============================================================
POTENZA   = 23.0      # dBm, EIRP do access point (Catalyst 9136)
FREQUENZA = 5000.0    # MHz, a banda de 5 GHz
SOGLIA_VERDE  = -65.0 # dBm: daqui para cima o sinal é bom
SOGLIA_GIALLA = -75.0 # dBm: entre os dois é fraco; abaixo, vermelho

# dB perdidos por centímetro de obstáculo, por categoria do vínculo
ATTENUAZIONE = {
    BuiltInCategory.OST_Walls:             0.6,
    BuiltInCategory.OST_Floors:            1.0,
    BuiltInCategory.OST_StructuralFraming: 1.0,
    BuiltInCategory.OST_StructuralColumns: 1.0,
    BuiltInCategory.OST_Roofs:             1.0,
}

FT_M = 0.3048           # pés -> metros, a Lei das unidades internas

# ============================================================
# 2. A SELEÇÃO: A ANTENA, OS PROBES, O VÍNCULO       [REVIT]
# ============================================================
print(">> Vá para o Revit: clique no access point (a antena Wi-Fi).")
rif = uidoc.Selection.PickObject(ObjectType.Element,
                                 "Clique no access point")
ap = doc.GetElement(rif.ElementId)
p_ap = punto(ap)
print("Access point: id {}".format(ap.Id))

print(">> Agora clique nos probes, um ou mais,"
      " e aperte CONCLUIR na barra de opções.")
riff = uidoc.Selection.PickObjects(ObjectType.Element,
                                   "Clique nos probes, depois CONCLUIR")
probes = [doc.GetElement(r.ElementId) for r in riff
          if r.ElementId != ap.Id]
print("Probes escolhidos: {}".format(len(probes)))

print(">> Por fim clique no vínculo (uma parede ou laje dele).")
rif = uidoc.Selection.PickObject(ObjectType.Element, "Clique no vínculo")
li = doc.GetElement(rif.ElementId)
if not isinstance(li, RevitLinkInstance):
    raise Exception("Isso não é um vínculo; clique num elemento "
                    "do modelo vinculado.")
ldoc = li.GetLinkDocument()
inv  = li.GetTotalTransform().Inverse
print("Vínculo: {}".format(ldoc.Title))

# ============================================================
# 3. OS OBSTÁCULOS DO VÍNCULO, COM A TRIAGEM           [ENG]
#    antes as caixas (grátis), a geometria real só para
#    os candidatos; os sólidos extraídos ficam em cache
# ============================================================
ostacoli = []                      # (bic, elemento, bbox)
for bic in ATTENUAZIONE:
    for el in (FilteredElementCollector(ldoc).OfCategory(bic)
               .WhereElementIsNotElementType()):
        bb = el.get_BoundingBox(None)
        if bb is not None:
            ostacoli.append((bic, el, bb))
print("Obstáculos no vínculo: {}".format(len(ostacoli)))

_cache = {}
def solidi_di(el):
    if el.Id not in _cache:
        raccolti = []
        geo = el.get_Geometry(Options())
        if geo is not None:
            for g in geo:
                if isinstance(g, Solid) and g.Volume > 0:
                    raccolti.append(g)
                elif isinstance(g, GeometryInstance):
                    for gg in g.GetInstanceGeometry():
                        if isinstance(gg, Solid) and gg.Volume > 0:
                            raccolti.append(gg)
        _cache[el.Id] = raccolti
    return _cache[el.Id]

def scatola_tocca(bb, a, b, gioco=0.5):
    return (min(a.X, b.X) - gioco <= bb.Max.X and
            max(a.X, b.X) + gioco >= bb.Min.X and
            min(a.Y, b.Y) - gioco <= bb.Max.Y and
            max(a.Y, b.Y) + gioco >= bb.Min.Y and
            min(a.Z, b.Z) - gioco <= bb.Max.Z and
            max(a.Z, b.Z) + gioco >= bb.Min.Z)

# ============================================================
# 4. O SINAL: ESPAÇO LIVRE + PEDÁGIOS                  [ENG]
#    FSPL = 20 log10(d) + 20 log10(f) - 27.55  (metri, MHz)
#    depois cada centímetro atravessado paga o seu pedágio
# ============================================================
opz = SolidCurveIntersectionOptions()
opz.ResultType = SolidCurveIntersectionMode.CurveSegmentsInside

risultati = []                     # (probe, rssi, veredito)
q_ap = inv.OfPoint(p_ap)           # a antena no mundo do vínculo
for pr in probes:
    p = punto(pr)
    if p is None:
        continue
    q = inv.OfPoint(p)             # o probe também viaja
    linea = Line.CreateBound(q_ap, q)
    d_m = q_ap.DistanceTo(q) * FT_M
    fspl = (20.0 * math.log10(max(d_m, 0.3))
            + 20.0 * math.log10(FREQUENZA) - 27.55)

    persi, attraversati, cm_totali = 0.0, 0, 0.0
    for bic, el, bb in ostacoli:
        if not scatola_tocca(bb, q_ap, q):
            continue
        dentro = 0.0
        for s in solidi_di(el):
            try:
                for seg in s.IntersectWithCurve(linea, opz):
                    dentro += seg.Length
            except:
                pass
        if dentro > 0:
            cm = dentro * 30.48
            persi += ATTENUAZIONE[bic] * cm
            attraversati += 1
            cm_totali += cm

    rssi = POTENZA - fspl - persi
    if rssi >= SOGLIA_VERDE:
        verdetto = "verde"
    elif rssi >= SOGLIA_GIALLA:
        verdetto = "amarelo"
    else:
        verdetto = "vermelho"
    risultati.append((pr, rssi, verdetto))
    print("Probe {}: {:.1f} m, esp. livre {:.1f} dB, "
          "{} obstáculos ({:.0f} cm) = {:.1f} dB -> {:.1f} dBm [{}]"
          .format(pr.Id, d_m, fspl, attraversati, cm_totali,
                  persi, rssi, verdetto.upper()))
