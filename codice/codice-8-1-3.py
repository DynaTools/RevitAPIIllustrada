# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.1.3  |  Capítulo 8.1 - O comprimento do circuito
# Seção: Passo 4 - sobra e comprimento total

# ============================================================
# 0. RECOMEÇO                              [PY]+[REVIT]+[ENG]
#    bloco autônomo: clique e some de novo o percurso
# ============================================================
from Autodesk.Revit.DB import LocationCurve
from Autodesk.Revit.UI.Selection import ObjectType

FT_M  = 0.3048
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
refs  = uidoc.Selection.PickObjects(ObjectType.Element,
                                    "Selecione todo o percurso, depois Finish")

def parametro(elem, *nomi):
    # parâmetros de família: o nome segue o idioma da família
    for nome in nomi:
        p = elem.LookupParameter(nome)
        if p:
            return p
    return None

# soma: trechos retos (curva) + conexões (arco = raio x ângulo)
L_ft = 0.0
for r in refs:
    elem_id = r.ElementId
    elem    = doc.GetElement(elem_id)
    loc     = elem.Location

    if isinstance(loc, LocationCurve):
        L_ft += loc.Curve.Length
    else:
        p_raggio = parametro(elem, "Bend Radius", "Raggio di curvatura")
        p_angolo = parametro(elem, "Angle", "Angolo")
        if p_raggio and p_angolo:
            L_ft += p_raggio.AsDouble() * p_angolo.AsDouble()

L_mod = L_ft * FT_M

# ============================================================
# 1. PASSO 4, SOBRA E TOTAL                              [ENG]
#    margem de instalação: terminações, reserva (%)
# ============================================================
sfrido_pct = 5.0
L_sfrido   = L_mod * sfrido_pct / 100.0
L_cavo     = L_mod + L_sfrido

# ============================================================
# 2. O RESULTADO                                         [OUT]
# ============================================================
print("Comprimento modelado: {:.2f} m".format(L_mod))
print("Sobra ({:.0f}%): {:.2f} m".format(sfrido_pct, L_sfrido))
print("---")
print("COMPRIMENTO DO CABO: {:.2f} m".format(L_cavo))
