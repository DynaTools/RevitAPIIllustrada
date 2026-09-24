# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 8.3.4  |  Capítulo 8.3 - A suportação
# Seção: Passo 4 - escrita no modelo, em transação

# ============================================================
# 0. RECOMEÇO                            [PY]+[REVIT]+[ENG]
#    bloco autônomo: recria o número de suportes N
# ============================================================
import math
from Autodesk.Revit.DB import Transaction
from Autodesk.Revit.UI.Selection import ObjectType

FT_M      = 0.3048
INTERASSE = 1.50

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document
ref   = uidoc.Selection.PickObject(ObjectType.Element,
                                   "Selecione a eletrocalha")
tray  = doc.GetElement(ref.ElementId)

L_run = tray.Location.Curve.Length * FT_M
N     = int(math.ceil(L_run / INTERASSE)) + 1

# ============================================================
# 1. PASSO 4, A ESCRITA NO MODELO              [REVIT] + [OUT]
#    Lei I: toda modificação vive numa Transaction.
#    LookupParameter -> None se o parâmetro não existe;
#    Set -> False se existe mas não pode ser escrito.
# ============================================================
par_n = tray.LookupParameter("Staffe n")
par_i = tray.LookupParameter("Staffe interasse")

if par_n is None or par_i is None:
    print("ERRO: faltam no trecho os parâmetros 'Staffe n'")
    print("e/ou 'Staffe interasse'. Crie-os como parâmetros de")
    print("projeto de INSTÂNCIA na categoria Eletrocalhas:")
    print("  Staffe n -> Inteiro, Staffe interasse -> Comprimento")
else:
    t = Transaction(doc, "Suportação EC-01")
    t.Start()
    ok_n = par_n.Set(N)
    ok_i = par_i.Set(INTERASSE / FT_M)     # em pés
    t.Commit()
    if ok_n and ok_i:
        print("Gravados no trecho: Staffe n = {}, "
              "interasse = {:.2f} m".format(N, INTERASSE))
    else:
        print("ERRO: escrita recusada (Set = False),")
        print("confira o tipo e a instância dos parâmetros.")
