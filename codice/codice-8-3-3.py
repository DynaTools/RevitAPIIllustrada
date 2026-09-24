# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.3.3  |  Capítulo 8.3 - A suportação
# Seção: Passo 3 - limites e verificação

# ============================================================
# 0. RECOMEÇO                            [PY]+[REVIT]+[ENG]
#    bloco autônomo: recria comprimento e peso por metro
# ============================================================
import math
from Autodesk.Revit.UI.Selection import ObjectType

FT_M = 0.3048
PESI = {"FG16 4G95": 4.10, "FG16 5G16": 1.35, "FG16 3G2.5": 0.18}
PESO_PASSERELLA = 5.00

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
ref   = uidoc.Selection.PickObject(ObjectType.Element,
                                   "Selecione a eletrocalha")
tray  = doc.GetElement(ref.ElementId)

L_run = tray.Location.Curve.Length * FT_M
w = PESO_PASSERELLA
for nome, peso in PESI.items():
    par = tray.LookupParameter(nome)
    w += peso * (par.AsInteger() if par else 0)

# ============================================================
# 1. PASSO 3, LIMITES E VERIFICAÇÃO                      [ENG]
#    carga por suporte, número de suportes, espaçamento
# ============================================================
G           = 9.81   # m/s^2
INTERASSE   = 1.50   # m, prática de catálogo
PORTATA     = 152.9  # kg, suporte 41/600: 1500 N (CEI EN 61537)
CAMPATA_MAX = 2.00   # m, do diagrama de carga

F   = w * INTERASSE                        # carga por suporte (kg)
F_N = F * G                                # em newtons
N   = int(math.ceil(L_run / INTERASSE)) + 1

i_max_staffa = PORTATA / w                 # limite do braço
i_ammesso    = min(i_max_staffa, CAMPATA_MAX)
conforme     = (F <= PORTATA) and (INTERASSE <= CAMPATA_MAX)

# ============================================================
# 2. O DESFECHO                                          [OUT]
# ============================================================
print("Peso do trecho: {:.1f} kg".format(w * L_run))
print("Carga por suporte: {:.1f} kg  ({:.0f} N)".format(F, F_N))
print("Número de suportes: {}".format(N))
print("Espaçamento admitido: {:.2f} m  (braço {:.2f} / vão {:.2f})".format(
    i_ammesso, i_max_staffa, CAMPATA_MAX))
print("RESULTADO: {}".format("CONFORME (margem {:.1f} kg)".format(PORTATA - F)
                             if conforme else "NÃO CONFORME"))
