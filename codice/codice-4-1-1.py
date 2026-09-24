# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.1.1  |  Capítulo 4.1 - Transações, o contrato antes de pôr a mão
# Seção: Por que o contrato existe

walls = FilteredElementCollector(doc).OfClass(Wall)  # R4 + R2

t = Transaction(doc, "Preencher Comentários")  # LEI I - o contrato
t.Start()
for w in walls:                            # R7 - for direto
    p = w.LookupParameter("Comentários")     # R2 - pega a ficha
    if p and not p.IsReadOnly:               # só se existe e é modificável
        p.Set("Verificado")
t.Commit()                                   # LEI I - assinar
