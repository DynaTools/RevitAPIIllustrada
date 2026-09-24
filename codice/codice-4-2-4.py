# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.2.4  |  Capítulo 4.2 - O método Spy → Replicar → Generalizar
# Seção: Generalizar, substituir o específico pela variável

from Autodesk.Revit.DB import Transaction

ids = list(uidoc.Selection.GetElementIds())
if not ids:                          # 1) nada selecionado?
    print("Selecione um elemento antes.")
else:
    el = doc.GetElement(ids[0])
    p = el.LookupParameter("Comentários") # 2) pode ser None
    if p and not p.IsReadOnly:            # 3) pode ser somente leitura
        t = Transaction(doc, "Verificado no selecionado")
        t.Start()
        p.Set("Verificado")
        t.Commit()
