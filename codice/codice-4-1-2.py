# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.1.2  |  Capítulo 4.1 - Transações, o contrato antes de pôr a mão
# Seção: Anatomia do contrato, do Start ao RollBack

t = Transaction(doc, "Preencher Comentários") # 1. redigir o contrato
t.Start()                                   # 2. abrir
# ... as modificações acontecem aqui ...
t.Commit()                                  # 3a. assinar (tornar efetivo)
# ou então: t.RollBack()                    # 3b. rasgar (desfazer tudo)
