# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 7.1.3  |  Capítulo 7.1 - A furação automática
# Seção: Passo 3 - os furos definitivos, Generic Model para a coordenação

# ============================================================
# 0. RETOMADA                                            [PY]
#    mesma sessão RPS: fori, cilindro(), ws_id e doc
#    ainda estão na memória
# ============================================================
from Autodesk.Revit.DB import (FilteredElementCollector,
    DirectShape, Transaction, ElementId, BuiltInCategory,
    BuiltInParameter, GeometryObject)
from System.Collections.Generic import List

MM_FT     = 1 / 304.8
categoria = ElementId(BuiltInCategory.OST_GenericModel)

# ============================================================
# 1. FORA AS MASSAS PROVISÓRIAS                        [REVIT]
#    os Passos 1--2 eram o teste; o modelo que se
#    compartilha não leva consigo as provas
# ============================================================
t = Transaction(doc, "Furação definitiva, Generic Model")
t.Start()

vecchie = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape):
    cat = ds.Category
    if cat is None:
        continue
    if cat.Id.IntegerValue != int(BuiltInCategory.OST_Mass):
        continue
    nome = ds.Name
    if nome.startswith("Clash eletroduto") or nome.startswith("Furo D"):
        vecchie.append(ds.Id)
for vid in vecchie:
    doc.Delete(vid)

# ============================================================
# 2. A COLOCAÇÃO DEFINITIVA                    [REVIT] + [OUT]
#    um Generic Model por furo, com Marca progressiva e
#    Comentários que dizem tudo: diâmetro, comprimento, eletroduto
# ============================================================
n = 0
for centro, direzione, raggio, lung, id_imp in fori:
    n += 1
    D = raggio * 2 / MM_FT            # diâmetro do furo, mm
    L = lung / MM_FT                  # comprimento do furo, mm
    ds = DirectShape.CreateElement(doc, categoria)
    ds.SetShape(List[GeometryObject](
        [cilindro(centro, direzione, raggio, lung)]))
    ds.SetName("Furo passante D{:.0f}".format(D))
    ds.get_Parameter(
        BuiltInParameter.ALL_MODEL_MARK).Set("F{:03d}".format(n))
    ds.get_Parameter(
        BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(
        "Furo passante D{:.0f} L{:.0f} - eletroduto {}".format(
            D, L, id_imp))
    if ws_id is not None:
        ds.get_Parameter(
            BuiltInParameter.ELEM_PARTITION_PARAM).Set(
            ws_id.IntegerValue)

t.Commit()

print("Massas provisórias removidas: {}".format(len(vecchie)))
print("Furos definitivos colocados: {}".format(n))
print("Categoria: Modelos genéricos, workset {}".format(
    NOME_WS if ws_id is not None else "(modelo não compartilhado)"))
print("O primeiro: Marca F001, veja Comentários para D, L e eletroduto.")
