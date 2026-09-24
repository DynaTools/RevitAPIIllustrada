# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.3.5  |  Capítulo 4.3 - Parâmetros em bloco
# Seção: Os None e os parâmetros somente leitura

count, skipped = 0, 0

t = Transaction(doc, "Preencher em bloco - defensivo")
t.Start()
for el in targets:
    p = el.LookupParameter("COD_AMBIENTE")
    if p and not p.IsReadOnly:        # a linha que salva o bloco
        p.Set(value)
        count += 1
    else:
        skipped += 1
t.Commit()

print(count, "preenchidos /", skipped, "pulados")
