# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.1.1  |  Capítulo 8.1 - O comprimento do circuito
# Seção: Passos 1--2 - medir o percurso a partir do modelo

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    bibliotecas e documento Revit ativo
# ============================================================
from Autodesk.Revit.DB import LocationCurve
from Autodesk.Revit.UI.Selection import ObjectType

FT_M = 0.3048                      # 1 pé = 0.3048 m

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

def parametro(elem, *nomi):
    # "Bend Radius" e "Angle" são parâmetros DE FAMÍLIA: o nome
    # segue o idioma da família carregada, e não existe um
    # BuiltInParameter que chegue até eles (Cap. 4.4). Tentam-se
    # os nomes um de cada vez: o primeiro que existir vence.
    for nome in nomi:
        p = elem.LookupParameter(nome)
        if p:
            return p
    return None

# ============================================================
# 1. PASSO 1, OS CLIQUES                               [REVIT]
#    o usuário seleciona TODO o percurso: trechos e conexões
# ============================================================
refs = uidoc.Selection.PickObjects(ObjectType.Element,
                                   "Selecione todo o percurso, depois Finish")

# ============================================================
# 2. PASSO 2, A SOMA 3D                        [REVIT] + [ENG]
#    trechos retos -> a sua curva; conexões -> o arco
# ============================================================
L_ft     = 0.0
n_tratti = 0
n_curve  = 0
n_muti   = 0                       # conexões sem os dois parâmetros

for r in refs:
    # um passo por linha, assim se vê tudo
    elem_id = r.ElementId                 # 1) o id do elemento
    elem    = doc.GetElement(elem_id)     # 2) o elemento propriamente dito
    loc     = elem.Location               # 3) a sua posição

    if isinstance(loc, LocationCurve):
        # trecho reto: tem uma curva de eixo
        curva = loc.Curve
        L_ft += curva.Length              # comprimento 3D, em pés
        n_tratti += 1
    else:
        # conexão (curva): o seu comprimento é o ARCO
        # arco = raio x ângulo  (o ângulo já está em radianos, Lei II)
        p_raggio = parametro(elem, "Bend Radius", "Raggio di curvatura")
        p_angolo = parametro(elem, "Angle", "Angolo")
        if p_raggio and p_angolo:
            raggio = p_raggio.AsDouble()  # raio de curvatura, em pés
            angolo = p_angolo.AsDouble()  # ângulo da dobra, em radianos
            L_ft += raggio * angolo       # comprimento do arco, em pés
        else:
            n_muti += 1                   # NUNCA pular em silêncio
        n_curve += 1

L_mod = L_ft * FT_M                    # comprimento modelado, em metros

# ============================================================
# 3. O RESULTADO                                         [OUT]
# ============================================================
print("Elementos selecionados: {}".format(len(refs)))
print("  trechos retos:    {}".format(n_tratti))
print("  conexões (arcos): {}".format(n_curve))
if n_muti:
    print("ATENÇÃO: {} conexões sem parâmetros!".format(n_muti))
print("Comprimento modelado (3D): {:.2f} m".format(L_mod))
