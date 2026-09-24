# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.4.3  |  Capítulo 8.4 - Distribuir com o esquema L-2L
# Seção: No Revit - lançar as luminárias em transação

# ============================================================
# 0. RECOMEÇO                              [PY]+[REVIT]+[ENG]
#    bloco autônomo: relê o ambiente, refaz passo e borda
# ============================================================
from Autodesk.Revit.DB import (XYZ, Transaction, Structure,
    FilteredElementCollector, BuiltInCategory, FamilySymbol, Level)
from Autodesk.Revit.UI.Selection import ObjectType

FT_M  = 0.3048
uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

ref = uidoc.Selection.PickObject(ObjectType.Element,
                                 "Selecione o ambiente")
bb  = doc.GetElement(ref.ElementId).get_BoundingBox(None)

x0 = bb.Min.X * FT_M;  A = (bb.Max.X - bb.Min.X) * FT_M
y0 = bb.Min.Y * FT_M;  B = (bb.Max.Y - bb.Min.Y) * FT_M
z  = bb.Max.Z * FT_M                       # cota do forro

nx, ny = 4, 3
sx = A / nx;  sy = B / ny

# ============================================================
# 1. OS PONTOS, GERADOS DE NOVO                  [PY] + [ENG]
#    a fórmula do centro, em forma compacta
# ============================================================
punti = []
for i in range(nx):
    for j in range(ny):
        punti.append(XYZ((x0 + (i + 0.5) * sx) / FT_M,
                         (y0 + (j + 0.5) * sy) / FT_M, z / FT_M))

# ============================================================
# 2. TIPO E NÍVEL                                      [REVIT]
#    o primeiro tipo de luminária e o primeiro nível
# ============================================================
symbol = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_LightingFixtures)\
    .OfClass(FamilySymbol).FirstElement()   # o primeiro tipo de luminária
level  = FilteredElementCollector(doc).OfClass(Level).FirstElement()

# ============================================================
# 3. O LANÇAMENTO, EM TRANSAÇÃO                [REVIT] + [OUT]
#    FirstElement -> None se faltar o tipo ou o nível
# ============================================================
if symbol is None or level is None:
    print("ERRO: falta no modelo um tipo de luminária")
    print("(ou um nível). Carregue uma família da")
    print("categoria Lighting Fixtures e tente de novo.")
else:
    if not symbol.IsActive:
        symbol.Activate()
    t = Transaction(doc, "Malha de luminárias L-2L")
    t.Start()
    for p in punti:
        doc.Create.NewFamilyInstance(
            p, symbol, level, Structure.StructuralType.NonStructural)
    t.Commit()
    print("{} luminárias lançadas na malha.".format(len(punti)))
