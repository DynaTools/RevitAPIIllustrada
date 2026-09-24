# -*- coding: utf-8 -*-
__title__ = "Rinomina\nWorkset"
__doc__ = "Renomeia os worksets do projeto a partir de uma interface."
__author__ = "Paulo Giavoni"

import clr
clr.AddReference("RevitAPI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import FilteredWorksetCollector, WorksetKind
from pyrevit import revit, forms, script

from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows.Markup import XamlReader
from System.Windows.Controls import TextBox, StackPanel
from System.Windows import Thickness

doc = revit.doc

if not doc.IsWorkshared:
    forms.alert("Este projeto não usa o Worksharing.",
                exitscript=True)

# ---------- Coleta os worksets ----------
worksets = (
    FilteredWorksetCollector(doc)
    .OfKind(WorksetKind.UserWorkset)
    .ToWorksets()
)

if not worksets:
    forms.alert("Nenhum workset encontrado.", exitscript=True)

ws_dict = {ws.Name: ws for ws in worksets}

# ---------- Interface (XAML escrito aqui, não num arquivo) ----------
xaml_str = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Renomear worksets"
        Width="500" Height="460"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize">
    <Border Padding="16">
        <Grid>
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>

            <TextBlock Grid.Row="0" Text="RENOMEAR WORKSETS" FontSize="15"
                       FontWeight="Bold" Foreground="#2C3E50" Margin="0,0,0,8"/>

            <TextBlock Grid.Row="1"
                       Text="Altere os nomes na coluna da direita:"
                       FontSize="12" Foreground="#555" Margin="0,0,0,6"/>

            <Grid Grid.Row="2" Margin="0,0,0,4">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="20"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0" Text="Nome atual" FontWeight="SemiBold"
                           FontSize="12" Foreground="#333"/>
                <TextBlock Grid.Column="1" Text="" />
                <TextBlock Grid.Column="2" Text="Novo nome" FontWeight="SemiBold"
                           FontSize="12" Foreground="#333"/>
            </Grid>

            <ScrollViewer Grid.Row="3" VerticalScrollBarVisibility="Auto"
                          Margin="0,0,0,12">
                <StackPanel x:Name="sp_worksets"/>
            </ScrollViewer>

            <TextBlock Grid.Row="4" x:Name="tb_status"
                       Foreground="#27AE60" FontSize="11" Margin="0,0,0,8"/>

            <StackPanel Grid.Row="5" Orientation="Horizontal"
                        HorizontalAlignment="Right">
                <Button x:Name="btn_rename" Content="Renomear" Width="100" Height="30"
                        Margin="0,0,8,0"
                        Background="#2C3E50" Foreground="White" FontWeight="SemiBold"/>
                <Button x:Name="btn_cancel" Content="Fechar" Width="100" Height="30"/>
            </StackPanel>
        </Grid>
    </Border>
</Window>
"""


class RenameWorksetUI(object):
    def __init__(self):
        xaml_bytes = Encoding.UTF8.GetBytes(xaml_str)
        stream = MemoryStream(xaml_bytes)
        self.window = XamlReader.Load(stream)

        self.sp_worksets = self.window.FindName("sp_worksets")
        self.tb_status = self.window.FindName("tb_status")
        self.btn_rename = self.window.FindName("btn_rename")
        self.btn_cancel = self.window.FindName("btn_cancel")

        self.rename_map = {}

        for name in sorted(ws_dict.keys()):
            row = StackPanel()
            row.Orientation = row.Orientation.Horizontal
            row.Margin = Thickness(0, 2, 0, 2)

            lbl = TextBox()
            lbl.Text = name
            lbl.Width = 200
            lbl.IsReadOnly = True
            lbl.Background = None
            lbl.BorderThickness = Thickness(0)
            lbl.FontSize = 12
            lbl.VerticalContentAlignment = lbl.VerticalContentAlignment.Center

            arrow = TextBox()
            arrow.Text = u"\u2192"
            arrow.Width = 30
            arrow.IsReadOnly = True
            arrow.Background = None
            arrow.BorderThickness = Thickness(0)
            arrow.FontSize = 14
            arrow.TextAlignment = arrow.TextAlignment.Center
            arrow.VerticalContentAlignment = arrow.VerticalContentAlignment.Center

            tb = TextBox()
            tb.Text = name
            tb.Width = 200
            tb.Height = 26
            tb.FontSize = 12
            tb.VerticalContentAlignment = tb.VerticalContentAlignment.Center
            tb.Padding = Thickness(4, 0, 4, 0)

            row.Children.Add(lbl)
            row.Children.Add(arrow)
            row.Children.Add(tb)
            self.sp_worksets.Children.Add(row)

            self.rename_map[name] = tb

        self.btn_rename.Click += self.on_rename
        self.btn_cancel.Click += self.on_cancel

    def on_rename(self, sender, args):
        self.window.DialogResult = True
        self.window.Close()

    def on_cancel(self, sender, args):
        self.window.DialogResult = False
        self.window.Close()

    def get_renames(self):
        result = {}
        for original, tb in self.rename_map.items():
            new_name = tb.Text.strip()
            if new_name and new_name != original:
                result[original] = new_name
        return result

    def show(self):
        return self.window.ShowDialog()


ui = RenameWorksetUI()
if not ui.show():
    script.exit()

renames = ui.get_renames()
if not renames:
    forms.alert("Nenhuma alteração.")
    script.exit()

# ---------- Renomeia, dentro de uma Transaction ----------
renamed = 0
with revit.Transaction("Renomear worksets"):
    for old_name, new_name in renames.items():
        ws = ws_dict.get(old_name)
        if ws:
            try:
                ws.Name = new_name
                renamed += 1
            except Exception:
                pass

righe = [u"'{}' \u2192 '{}'".format(o, n) for o, n in renames.items()]
forms.alert(
    "{} worksets renomeados:\n\n{}".format(renamed, "\n".join(righe))
)
