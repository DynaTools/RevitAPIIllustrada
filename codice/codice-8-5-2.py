# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.5.2  |  Capítulo 8.5 - O cálculo luminotécnico ponto a ponto
# Seção: Passo 2 - a malha de probes, o mapa de calor

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    para rodar numa PLANTA do nível a verificar
# ============================================================
import math
from Autodesk.Revit.DB import (FilteredElementCollector, Transaction,
    BuiltInCategory, BuiltInParameter, LocationPoint, XYZ,
    FamilySymbol, FamilyInstance, OverrideGraphicSettings, Color,
    FillPatternElement)
from Autodesk.Revit.DB.Structure import StructuralType

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

# ============================================================
# 1. O CADERNO FOTOMÉTRICO                              [ENG]
# ============================================================
INTENSITA    = 1200.0   # cd para baixo, por luminária
QUOTA_MISURA = 0.85     # m acima do piso
SOGLIA       = 75.0     # lux, UNI EN 12464-1 para o estacionamento
PASSO        = 0.3      # m entre um probe e outro
SOFFITTO_MAX = 6.0      # m: luminárias mais altas não contam
FAMIGLIA     = "Probe_LUX"

FT_M = 0.3048           # pés -> metros, a Lei das unidades internas

def punto(el):
    loc = el.Location
    if isinstance(loc, LocationPoint):
        return loc.Point
    bb = el.get_BoundingBox(None)
    return (bb.Min + bb.Max) / 2.0 if bb else None

# a escala de calor, de 0 (frio) a 1 (quente); como nas
# câmeras térmicas, os extremos se prendem aos valores medidos
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
# 2. AS LUMINÁRIAS E A FAMÍLIA DO PROBE               [REVIT]
#    as luminárias se coletam sozinhas; o probe já deve
#    estar carregado no modelo
# ============================================================
apparecchi = []
for el in (FilteredElementCollector(doc)
           .OfCategory(BuiltInCategory.OST_LightingFixtures)
           .WhereElementIsNotElementType()):
    s = punto(el)
    if s is not None:
        apparecchi.append(s)
print("Luminárias no modelo: {}"
      .format(len(apparecchi)))

simbolo = None
for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
    if fs.Family.Name == FAMIGLIA:
        simbolo = fs
        break
if simbolo is None:
    raise Exception("Carregue antes a família {}.".format(FAMIGLIA))

vista = doc.ActiveView
livello = vista.GenLevel
if livello is None:
    raise Exception("Abra a PLANTA do nível a verificar "
                    "e rode o script de novo.")

# ============================================================
# 3. O RETÂNGULO E A MALHA                            [REVIT]
#    dois cliques em planta, os cantos opostos da área
# ============================================================
print(">> Vá para o Revit: clique nos DOIS cantos opostos da área"
      " a verificar, na planta.")
a = uidoc.Selection.PickPoint("Primeiro canto da área")
b = uidoc.Selection.PickPoint("Segundo canto, oposto")

x0, x1 = min(a.X, b.X), max(a.X, b.X)
y0, y1 = min(a.Y, b.Y), max(a.Y, b.Y)
passo = PASSO / FT_M
nx = max(1, int((x1 - x0) / passo) + 1)
ny = max(1, int((y1 - y0) / passo) + 1)
print("Malha {} x {} = {} probes, passo {:.1f} m"
      .format(nx, ny, nx * ny, PASSO))

def lux_in(p):
    E = 0.0
    for s in apparecchi:
        dz = (s.Z - p.Z) * FT_M
        if dz <= 0 or dz > SOFFITTO_MAX:
            continue
        d = s.DistanceTo(p) * FT_M
        E += INTENSITA * (dz / d) / (d * d)
    return E

# ============================================================
# 4. PRIMEIRO SE MEDE TUDO                              [ENG]
#    duas passadas: a escala de cor precisa
#    conhecer o mínimo e o máximo ANTES de pintar
# ============================================================
punti, valori = [], []
for i in range(nx):
    for j in range(ny):
        p = XYZ(x0 + i * passo, y0 + j * passo, livello.Elevation)
        p_mis = XYZ(p.X, p.Y, p.Z + QUOTA_MISURA / FT_M)
        punti.append(p)
        valori.append(lux_in(p_mis))

minimo, massimo = min(valori), max(valori)
ampiezza = (massimo - minimo) or 1.0
print("Escala de cor: azul em {:.0f} lux, vermelho em {:.0f}"
      .format(minimo, massimo))

# ============================================================
# 5. INSERÇÃO E COR                           [REVIT] + [OUT]
#    uma transação só: os probes nascem e se acendem
#    na sua cor; os lux vão para os Comentários
# ============================================================
riempimento = None
for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
    if fp.GetFillPattern().IsSolidFill:
        riempimento = fp.Id
        break

t = Transaction(doc, "A malha de probes")
t.Start()
if not simbolo.IsActive:
    simbolo.Activate()

# reexecutável: os probes da rodada anterior são removidos
vecchi = [el.Id for el in FilteredElementCollector(doc)
          .OfClass(FamilyInstance)
          if el.Symbol.Family.Name == FAMIGLIA]
for eid in vecchi:
    doc.Delete(eid)
if vecchi:
    print("Probes da rodada anterior removidos: {}".format(len(vecchi)))

for p, E in zip(punti, valori):
    pr = doc.Create.NewFamilyInstance(
        p, simbolo, livello, StructuralType.NonStructural)
    # o probe DEVE ficar no nível: alguns overloads somam a
    # cota do ponto como offset, e nos níveis enterrados (cota
    # negativa) a instância acabaria debaixo da terra
    off = pr.get_Parameter(BuiltInParameter.INSTANCE_ELEVATION_PARAM)
    if off is not None and not off.IsReadOnly:
        off.Set(0.0)
    ogs = OverrideGraphicSettings()
    col = colore((E - minimo) / ampiezza)
    ogs.SetProjectionLineColor(col)
    if riempimento is not None:
        ogs.SetSurfaceForegroundPatternId(riempimento)
        ogs.SetSurfaceForegroundPatternColor(col)
    vista.SetElementOverrides(pr.Id, ogs)
    par = pr.get_Parameter(
        BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if par is not None:
        par.Set("Lux {:.0f}".format(E))
t.Commit()

# ============================================================
# 6. A NORMA, SOBRE OS NÚMEROS REAIS                    [OUT]
#    média, mínimo e uniformidade U0 = Emin / Emédia
# ============================================================
media = sum(valori) / len(valori)
minimo, massimo = min(valori), max(valori)
u0 = minimo / media if media > 0 else 0.0
sotto = sum(1 for v in valori if v < SOGLIA)
print("Probes inseridos: {}".format(len(valori)))
print("  Emédia {:.1f} lux   Emin {:.1f}   Emax {:.1f}"
      .format(media, minimo, massimo))
print("  U0 = Emin/Emédia = {:.2f}".format(u0))
print("  abaixo do limiar de {:.0f} lux: {} probes"
      .format(SOGLIA, sotto))
