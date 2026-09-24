# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.4.7  |  Capítulo 8.4 - Distribuir com o esquema L-2L
# Seção: A mesma música na parede, as tomadas

# ============================================================
# 0. RECOMEÇO                                            [PY]
#    mesma sessão: wall e punti na memória
# ============================================================
from Autodesk.Revit.DB import (Transaction, Structure, Line, XYZ,
    ElementTransformUtils, FilteredElementCollector, BuiltInCategory,
    FamilySymbol)

# ============================================================
# 1. O TIPO DE TOMADA, O NÍVEL, O SENTIDO            [REVIT]
# ============================================================
symbol = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_ElectricalFixtures)\
    .OfClass(FamilySymbol).FirstElement()    # primeiro tipo de tomada carregado
level  = doc.GetElement(wall.LevelId)        # o nível da parede

n = wall.Orientation                # normal da parede: para fora
verso_stanza = -n                   # as tomadas olham para dentro

if not symbol.IsActive:
    symbol.Activate()

# ============================================================
# 2. O LANÇAMENTO ORIENTADO, EM TRANSAÇÃO    [REVIT] + [OUT]
# ============================================================
t = Transaction(doc, "Distribuição de tomadas")
t.Start()
for p in punti:
    inst = doc.Create.NewFamilyInstance(
        p, symbol, level, Structure.StructuralType.NonStructural)
    doc.Regenerate()                        # atualiza a orientação
    attuale = inst.FacingOrientation        # para onde a tomada olha agora
    angolo  = attuale.AngleTo(verso_stanza) # quanto girá-la
    if attuale.CrossProduct(verso_stanza).Z < 0:
        angolo = -angolo                    # sinal da rotação (eixo Z)
    asse = Line.CreateBound(p, p + XYZ.BasisZ)
    ElementTransformUtils.RotateElement(doc, inst.Id, asse, angolo)
t.Commit()

print("{} tomadas lançadas na parede, voltadas para o ambiente.".format(
    len(punti)))
