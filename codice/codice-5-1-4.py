# -*- coding: utf-8 -*-
# Revit API Ilustrada em Python - Paulo Giavoni
# Código 5.1.4  |  Capítulo 5.1 - pyRevit, botões e distribuição
# Seção: Perguntar ao usuário, uma janela em XAML

from pyrevit import forms


class Finestra(forms.WPFWindow):
    def __init__(self):
        # carrega o .xaml que fica ao lado do script
        forms.WPFWindow.__init__(self, "Finestra.xaml")
        self.risposta = None

    # método ligado a  Click="ok_click"  no XAML
    def ok_click(self, sender, args):
        # self.valore = a TextBox  x:Name="valore"
        self.risposta = float(self.valore.Text)
        self.Close()


f = Finestra()
f.show_dialog()              # abre a janela e espera
if f.risposta is not None:
    forms.alert("Entre-eixo: {} m".format(f.risposta))
