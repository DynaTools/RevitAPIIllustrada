# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.5.3  |  Capítulo 8.5 - O cálculo luminotécnico ponto a ponto
# Seção: Passo 3 - o mapa se reacende em qualquer vista

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    para rodar na vista a pintar (o 3D, a planta, um
#    corte): as substituições gráficas valem por vista
# ============================================================
from Autodesk.Revit.DB import (FilteredElementCollector, Transaction,
    BuiltInParameter, FamilyInstance, OverrideGraphicSettings,
    Color, FillPatternElement)

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

FAMIGLIA = "Probe_LUX"

TAPPE = [(0.00, (30, 60, 200)),  (0.25, (0, 170, 200)),
         (0.50, (0, 150, 0)),    (0.75, (235, 170, 0)),
         (1.00, (200, 30, 30))]

def colore(x):
    x = max(0.0, min(1.0, x))
    for (x0, c0), (x1, c1) in zip(TAPPE, TAPPE[1:]):
        if x <= x1:
            f = (x - x0) / (x1 - x0)
            return Color(int(c0[0] + f * (c1[0] - c0[0])),
                         int(c0[1] + f * (c1[1] - c0[1])),
                         int(c0[2] + f * (c1[2] - c0[2])))
    r, g, b = TAPPE[-1][1]
    return Color(r, g, b)

# ============================================================
# 1. OS PROBES E OS SEUS LUX, DOS COMENTÁRIOS         [REVIT]
#    a medida já está no modelo: relê-se, não se
#    recalcula
# ============================================================
probe = []
for el in FilteredElementCollector(doc).OfClass(FamilyInstance):
    if el.Symbol.Family.Name != FAMIGLIA:
        continue
    par = el.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    testo = par.AsString() if par is not None else None
    if testo and testo.startswith("Lux "):
        try:
            probe.append((el, float(testo[4:])))
        except ValueError:
            pass
print("Probes com uma medida nos Comentários: {}".format(len(probe)))
if not probe:
    raise Exception("Nenhum probe medido; rode antes a malha.")

valori = [v for _, v in probe]
minimo, massimo = min(valori), max(valori)
ampiezza = (massimo - minimo) or 1.0
print("Escala de cor: azul em {:.0f} lux, vermelho em {:.0f}"
      .format(minimo, massimo))

# ============================================================
# 2. A VISTA ATIVA SE ACENDE                   [REVIT] + [OUT]
# ============================================================
riempimento = None
for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
    if fp.GetFillPattern().IsSolidFill:
        riempimento = fp.Id
        break

vista = doc.ActiveView
t = Transaction(doc, "O mapa de calor na vista ativa")
t.Start()
for el, E in probe:
    col = colore((E - minimo) / ampiezza)
    ogs = OverrideGraphicSettings()
    ogs.SetProjectionLineColor(col)
    if riempimento is not None:
        ogs.SetSurfaceForegroundPatternId(riempimento)
        ogs.SetSurfaceForegroundPatternColor(col)
    vista.SetElementOverrides(el.Id, ogs)
t.Commit()

print("Probes acesos na vista '{}': {}".format(vista.Name, len(probe)))
