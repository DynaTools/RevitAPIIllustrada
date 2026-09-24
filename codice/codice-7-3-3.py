# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 7.3.3  |  Capítulo 7.3 - A WBS, o modelo classificado
# Seção: Passo 3 - aplicar a classificação revisada

# ============================================================
# 0. PREPARAÇÃO                                 [PY] + [REVIT]
#    lê-se a tabela REVISADA no Excel, não o modelo:
#    entre os dois passos houve o julgamento do coordenador
# ============================================================
import os, csv
from Autodesk.Revit.DB import ElementId, Transaction

uidoc = __revit__.ActiveUIDocument
doc   = uidoc.Document

percorso = os.path.join(os.path.expanduser("~"), "Documents",
                        "wbs_elementos.csv")
CAMPI = ["WBS_s01", "WBS_s02", "WBS_s03", "WBS_t01", "WBS_t02"]

righe = []
with open(percorso) as f:
    for r in csv.DictReader(f, delimiter=";"):
        righe.append(r)
print("Linhas lidas: {} de {}".format(len(righe), percorso))

# ============================================================
# 1. A ESCRITA, UMA SÓ TRANSAÇÃO              [REVIT] + [OUT]
#    cinco campos mais o código completo agregado; quem não
#    tem os parâmetros é contado, nunca perdido em silêncio
# ============================================================
pieni, salti = 0, 0
t = Transaction(doc, "Aplicar a WBS")
t.Start()
for r in righe:
    el = doc.GetElement(ElementId(int(r["Id"])))
    if el is None:
        salti += 1
        continue
    ok = True
    for campo in CAMPI:
        par = el.LookupParameter(campo)
        if par is None:
            ok = False                # parâmetro não vinculado aqui
            continue
        par.Set(r[campo] or "")
    codice = "-".join(r[c] for c in CAMPI if r[c])
    par = el.LookupParameter("WBS_CODIGO")
    if par is not None:
        par.Set(codice)
    else:
        ok = False
    if ok:
        pieni += 1
    else:
        salti += 1
t.Commit()

print("Elementos completos: {}".format(pieni))
print("Elementos pulados (sem parâmetros): {}".format(salti))
esempio = next((r for r in righe if r["WBS_s03"] != "EXT"), None)
if esempio:
    print("Um exemplo: {} -> {}".format(
        esempio["Id"],
        "-".join(esempio[c] for c in CAMPI if esempio[c])))
