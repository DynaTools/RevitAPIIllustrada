# -*- coding: utf-8 -*-
__title__ = "Delete All\nView Templates"
__doc__ = "Delete View Templates from the current project with a selection UI."
__author__ = "Paulo Giavoni"

import clr
clr.AddReference("RevitAPI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import FilteredElementCollector, View
from pyrevit import revit, forms, script

from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows.Markup import XamlReader

doc = revit.doc

# ---------- Coletar View Templates ----------
templates = [
    v for v in FilteredElementCollector(doc).OfClass(View)
    if v.IsTemplate
]

if not templates:
    forms.alert("No View Template found in the project.", exitscript=True)

template_dict = {t.Name: t for t in templates}

# ---------- UI ----------
xaml_str = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Delete View Templates"
        Width="420" Height="520"
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

            <TextBlock Grid.Row="0" Text="DELETE VIEW TEMPLATES" FontSize="15"
                       FontWeight="Bold" Foreground="#2C3E50" Margin="0,0,0,8"/>

            <TextBlock Grid.Row="1" Text="Select the templates to delete:"
                       FontSize="12" Foreground="#555" Margin="0,0,0,6"/>

            <StackPanel Grid.Row="2" Orientation="Horizontal" Margin="0,0,0,6">
                <Button x:Name="btn_all" Content="Select All"
                        Width="110" Height="24" FontSize="11" Margin="0,0,6,0"/>
                <Button x:Name="btn_none" Content="Clear Selection"
                        Width="110" Height="24" FontSize="11" Margin="0,0,6,0"/>
                <TextBox x:Name="tb_search" Width="150" Height="24"
                         VerticalContentAlignment="Center" FontSize="11"/>
            </StackPanel>

            <ListBox Grid.Row="3" x:Name="lb_templates" Margin="0,0,0,8"
                     SelectionMode="Extended"/>

            <TextBlock Grid.Row="4" x:Name="tb_count"
                       Foreground="#C0392B" FontSize="12" FontWeight="SemiBold"
                       Margin="0,0,0,10"/>

            <StackPanel Grid.Row="5" Orientation="Horizontal"
                        HorizontalAlignment="Right">
                <Button x:Name="btn_delete" Content="Delete" Width="100" Height="30"
                        IsEnabled="False" Margin="0,0,8,0"
                        Background="#C0392B" Foreground="White" FontWeight="SemiBold"/>
                <Button x:Name="btn_cancel" Content="Cancel" Width="100" Height="30"/>
            </StackPanel>
        </Grid>
    </Border>
</Window>
"""


class DeleteTemplatesUI(object):
    def __init__(self):
        xaml_bytes = Encoding.UTF8.GetBytes(xaml_str)
        stream = MemoryStream(xaml_bytes)
        self.window = XamlReader.Load(stream)

        self.lb_templates = self.window.FindName("lb_templates")
        self.tb_count = self.window.FindName("tb_count")
        self.tb_search = self.window.FindName("tb_search")
        self.btn_all = self.window.FindName("btn_all")
        self.btn_none = self.window.FindName("btn_none")
        self.btn_delete = self.window.FindName("btn_delete")
        self.btn_cancel = self.window.FindName("btn_cancel")

        self.all_names = sorted(template_dict.keys())
        self.selected = []

        for name in self.all_names:
            self.lb_templates.Items.Add(name)

        self.tb_count.Text = "0 of {} selected".format(len(self.all_names))

        self.lb_templates.SelectionChanged += self.on_selection
        self.btn_all.Click += self.on_select_all
        self.btn_none.Click += self.on_select_none
        self.btn_delete.Click += self.on_delete
        self.btn_cancel.Click += self.on_cancel
        self.tb_search.TextChanged += self.on_search

    def on_search(self, sender, args):
        query = self.tb_search.Text.lower()
        self.lb_templates.Items.Clear()
        for name in self.all_names:
            if query in name.lower():
                self.lb_templates.Items.Add(name)

    def on_selection(self, sender, args):
        count = self.lb_templates.SelectedItems.Count
        self.tb_count.Text = "{} of {} selected".format(
            count, self.lb_templates.Items.Count
        )
        self.btn_delete.IsEnabled = count > 0

    def on_select_all(self, sender, args):
        self.lb_templates.SelectAll()

    def on_select_none(self, sender, args):
        self.lb_templates.UnselectAll()

    def on_delete(self, sender, args):
        self.selected = [
            item for item in self.lb_templates.SelectedItems
        ]
        self.window.DialogResult = True
        self.window.Close()

    def on_cancel(self, sender, args):
        self.window.DialogResult = False
        self.window.Close()

    def show(self):
        return self.window.ShowDialog()


ui = DeleteTemplatesUI()
if not ui.show():
    script.exit()

if not ui.selected:
    script.exit()

# ---------- Confirm ----------
confirm = forms.alert(
    "Are you sure you want to delete {} View Templates?".format(len(ui.selected)),
    yes=True,
    no=True,
)
if not confirm:
    script.exit()

# ---------- Delete ----------
deleted = 0
with revit.Transaction("Delete View Templates"):
    for name in ui.selected:
        t = template_dict.get(name)
        if t:
            try:
                doc.Delete(t.Id)
                deleted += 1
            except Exception:
                pass

forms.alert("{} View Templates deleted.".format(deleted))
