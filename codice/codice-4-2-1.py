# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.2.1  |  Capítulo 4.2 - O método Spy → Replicar → Generalizar
# Seção: Replicar, o caso mais simples que funciona

target = uidoc.Selection.GetElementIds()      # o elemento selecionado
el = doc.GetElement(list(target)[0])          # pega o primeiro (e único)

t = Transaction(doc, "Replicar - teste")    # LEI I
t.Start()
el.LookupParameter("Comentários").Set("TESTE-REPLICAR")
t.Commit()
