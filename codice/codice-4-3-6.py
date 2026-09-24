# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 4.3.6  |  Capítulo 4.3 - Parâmetros em bloco
# Seção: Parâmetros compartilhados e de projeto

from System import Guid

guid = Guid("a1b2c3d4-0000-0000-0000-00000000beba")  # copiado do .txt do BEP
p = el.get_Parameter(guid)        # acha pelo passaporte, não pelo apelido
if p and not p.IsReadOnly:
    p.Set(value)
