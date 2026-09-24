# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 7.2.2  |  Capítulo 7.2 - Onde está cada elemento
# Seção: Passo 3 - o ambiente, do link de arquitetura

# ============================================================
# 0. RETOMADA                                            [PY]
#    mesma sessão RPS: punto() e doc ainda estão na memória
# ============================================================
from Autodesk.Revit.DB import (FilteredElementCollector,
    RevitLinkInstance, BuiltInCategory, BuiltInParameter)
from Autodesk.Revit.UI.Selection import ObjectType

# ============================================================
# 1. OS AMBIENTES VIVEM NO LINK                        [REVIT]
#    os Room ficam no modelo de arquitetura; de cada link
#    com ambientes guarda-se a transformação INVERSA, porque
#    desta vez é o nosso ponto que vai para o mundo do link
# ============================================================
gruppi_locali = []
for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
    ldoc = li.GetLinkDocument()
    if ldoc is None:
        continue                      # link descarregado
    stanze = list(FilteredElementCollector(ldoc)
                  .OfCategory(BuiltInCategory.OST_Rooms)
                  .WhereElementIsNotElementType())
    stanze = [s for s in stanze if s.Area > 0]   # sem ambientes vazios
    if stanze:
        gruppi_locali.append((li.GetTotalTransform().Inverse, stanze))
        print("Link com ambientes: {} ({})".format(ldoc.Title, len(stanze)))

# ============================================================
# 2. O PONTO NO AMBIENTE                        [ENG] + [REVIT]
#    a pergunta exata é Room.IsPointInRoom; a resposta
#    só chega se o ponto fala a língua do link
# ============================================================
def locale(p):
    if p is None:
        return None
    for inv, stanze in gruppi_locali:
        q = inv.OfPoint(p)            # o nosso mundo -> o link
        for s in stanze:
            if s.IsPointInRoom(q):
                return s
    return None                       # externo, ou shaft sem Room

# ============================================================
# 3. O TESTE NOS MESMOS ELEMENTOS                        [OUT]
# ============================================================
print("")
print(">> Vá para o Revit: clique 3-4 elementos no modelo,")
print(">> depois aperte CONCLUIR na barra de opções.")
riff = uidoc.Selection.PickObjects(ObjectType.Element,
    "Clique os elementos, depois CONCLUIR na barra de opções")
for rif in riff:
    el = doc.GetElement(rif.ElementId)
    p, come = punto(el)
    s = locale(p)
    if s is not None:
        num  = s.get_Parameter(BuiltInParameter.ROOM_NUMBER).AsString()
        nome = s.get_Parameter(BuiltInParameter.ROOM_NAME).AsString()
        print("{} {}: ambiente {} {}".format(
            el.Id, el.Category.Name, num, nome))
    else:
        print("{} {}: nenhum ambiente (externo?)".format(
            el.Id, el.Category.Name))
