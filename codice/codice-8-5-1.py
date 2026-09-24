# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.5.1  |  Capítulo 8.5 - O cálculo luminotécnico ponto a ponto
# Seção: Passo 1 - o probe, as luminárias, os lux

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
# ============================================================
import math
from Autodesk.Revit.DB import (BuiltInParameter, Transaction,
    LocationPoint, XYZ)
from Autodesk.Revit.UI.Selection import ObjectType

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# ============================================================
# 1. O CADERNO FOTOMÉTRICO                              [ENG]
#    intensidade da luminária, cota do plano de
#    medição e limiar da norma: valores, não algoritmo
# ============================================================
INTENSITA    = 1200.0   # cd, para baixo (da fotometria)
QUOTA_MISURA = 0.85     # m acima do ponto de inserção do probe
SOGLIA       = 75.0     # lux, UNI EN 12464-1 para o estacionamento

FT_M = 0.3048           # pés -> metros, a Lei das unidades internas

def punto(el):
    loc = el.Location
    if isinstance(loc, LocationPoint):
        return loc.Point
    bb = el.get_BoundingBox(None)
    return (bb.Min + bb.Max) / 2.0 if bb else None

# ============================================================
# 2. A SELEÇÃO: AS LUMINÁRIAS E O PROBE               [REVIT]
# ============================================================
print(">> Vá para o Revit: clique nas luminárias,"
      " depois aperte CONCLUIR na barra de opções.")
riff = uidoc.Selection.PickObjects(ObjectType.Element,
                                   "Clique nas luminárias, depois CONCLUIR")
apparecchi = [doc.GetElement(r.ElementId) for r in riff]
print("Luminárias escolhidas: {}".format(len(apparecchi)))

print(">> Agora clique no probe.")
rif = uidoc.Selection.PickObject(ObjectType.Element, "Clique no probe")
probe = doc.GetElement(rif.ElementId)
print("Probe: id {}".format(probe.Id))

# ============================================================
# 3. O PONTO A PONTO                                    [ENG]
#    cada luminária contribui com I*cos(theta)/d^2;
#    theta a partir da vertical, d em metros, tudo somado
# ============================================================
base = punto(probe)
p_mis = XYZ(base.X, base.Y, base.Z + QUOTA_MISURA / FT_M)

E = 0.0
contributi = []
for ap in apparecchi:
    s = punto(ap)
    if s is None:
        continue
    dz = (s.Z - p_mis.Z) * FT_M     # a luminária fica acima
    if dz <= 0:
        continue
    d = s.DistanceTo(p_mis) * FT_M
    cos = dz / d
    e = INTENSITA * cos / (d * d)
    E += e
    contributi.append((e, ap.Id, d))

contributi.sort(reverse=True)
print("Plano de medição: {:.2f} m acima da inserção do probe"
      .format(QUOTA_MISURA))
for e, eid, d in contributi[:3]:
    print("  luminária {}: {:.1f} m -> {:.1f} lux".format(eid, d, e))
if len(contributi) > 3:
    print("  ... e mais {} luminárias".format(len(contributi) - 3))
print("Iluminância no probe: {:.1f} lux  (limiar {:.0f})"
      .format(E, SOGLIA))

# ============================================================
# 4. O RESULTADO NOS COMENTÁRIOS              [REVIT] + [OUT]
# ============================================================
t = Transaction(doc, "Lux no probe")
t.Start()
par = probe.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
if par is not None:
    par.Set("Lux {:.0f}".format(E))
t.Commit()
print("Comentários atualizados.")
