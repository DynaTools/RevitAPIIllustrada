# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 7.2.3  |  Capítulo 7.2 - Onde está cada elemento
# Seção: Passo 4 - o smart location escreve no modelo

# ============================================================
# 0. RETOMADA                                            [PY]
#    mesma sessão: punto(), livello_dichiarato(),
#    livello_dalla_quota() e gruppi_locali na memória
# ============================================================
from Autodesk.Revit.DB import (FilteredElementCollector,
    BuiltInCategory, BuiltInParameter, Transaction)

CATEGORIE = [BuiltInCategory.OST_Conduit,
             BuiltInCategory.OST_ConduitFitting,
             BuiltInCategory.OST_CableTray,
             BuiltInCategory.OST_CableTrayFitting,
             BuiltInCategory.OST_ElectricalEquipment,
             BuiltInCategory.OST_ElectricalFixtures,
             BuiltInCategory.OST_LightingFixtures,
             BuiltInCategory.OST_LightingDevices,
             BuiltInCategory.OST_DataDevices,
             BuiltInCategory.OST_CommunicationDevices,
             BuiltInCategory.OST_FireAlarmDevices,
             BuiltInCategory.OST_SecurityDevices]

# ============================================================
# 1. A TRIAGEM, DE NOVO                                  [ENG]
#    IsPointInRoom é caro, e aqui é feito milhares de vezes:
#    antes a caixa do ambiente, quase de graça, DEPOIS a pergunta
# ============================================================
scatole = []
for inv, stanze in gruppi_locali:
    coppie = []
    for s in stanze:
        bb = s.get_BoundingBox(None)
        if bb is not None:
            coppie.append((s, bb))
    scatole.append((inv, coppie))

def locale_veloce(p, gioco=0.5):
    if p is None:
        return None
    for inv, coppie in scatole:
        q = inv.OfPoint(p)            # o nosso mundo -> o link
        for s, bb in coppie:
            if (bb.Min.X - gioco <= q.X <= bb.Max.X + gioco and
                    bb.Min.Y - gioco <= q.Y <= bb.Max.Y + gioco and
                    bb.Min.Z - gioco <= q.Z <= bb.Max.Z + gioco):
                if s.IsPointInRoom(q):
                    return s
    return None

# ============================================================
# 2. UMA LINHA QUE DIZ ONDE                              [ENG]
#    nível + ambiente numa string que qualquer um lê:
#    "Level 1 | 101 Escritório", ou então "Level 1 | externo"
# ============================================================
def dove(el):
    p = punto(el)[0]
    if p is None:
        return None
    liv = livello_dichiarato(el) or livello_dalla_quota(p.Z)
    s = locale_veloce(p)
    if s is not None:
        num  = s.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString()
        nome = s.get_Parameter(BuiltInParameter.ROOM_NAME).AsString()
        return "{} | {} {}".format(liv, num, nome)
    return "{} | externo".format(liv)

# ============================================================
# 3. A ESCRITA EM TRANSAÇÃO                    [REVIT] + [OUT]
#    o resultado vai nos Comentários: visível em toda tabela,
#    em todo filtro, em todo ambiente de coordenação
# ============================================================
elementi = []
for cat in CATEGORIE:
    elementi += list(FilteredElementCollector(doc)
                     .OfCategory(cat).WhereElementIsNotElementType())

scritti, senza_locale, senza_punto = 0, 0, 0
esempio = None
t = Transaction(doc, "Smart location nos Comentários")
t.Start()
for el in elementi:
    riga = dove(el)
    if riga is None:
        senza_punto += 1
        continue
    if riga.endswith("externo"):
        senza_locale += 1
    elif esempio is None:
        esempio = (el.Id, riga)
    el.get_Parameter(
        BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(riga)
    scritti += 1
t.Commit()

print("Elementos examinados: {}".format(len(elementi)))
print("Comentários escritos: {}".format(scritti))
print("  sem ambiente (externos ou shafts): {}".format(senza_locale))
print("  sem ponto:                         {}".format(senza_punto))
if esempio is not None:
    print("Um exemplo: {} -> {}".format(*esempio))
