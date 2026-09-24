# -*- coding: utf-8 -*-
__title__ = "Copy Linked\nElements"
__doc__ = "Select a link and a category to copy elements from the linked model to the current project."
__author__ = "Paulo Giavoni"

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    RevitLinkInstance,
    CopyPasteOptions,
    ElementTransformUtils,
    ElementId,
    IDuplicateTypeNamesHandler,
    DuplicateTypeAction,
)
from pyrevit import revit, forms, script
from System.Collections.Generic import List as NetList

from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows.Markup import XamlReader

doc = revit.doc
uidoc = revit.uidoc


class CopyHandler(IDuplicateTypeNamesHandler):
    """Use destination types when duplicates exist."""
    def OnDuplicateTypeNamesFound(self, args):
        return DuplicateTypeAction.UseDestinationTypes

# ---------- Collect Links ----------
links = (
    FilteredElementCollector(doc)
    .OfClass(RevitLinkInstance)
    .ToElements()
)

if not links:
    forms.alert("No Revit Link found in the project.", exitscript=True)

link_dict = {}
for lnk in links:
    link_doc = lnk.GetLinkDocument()
    if link_doc:
        name = link_doc.Title
        link_dict[name] = lnk

if not link_dict:
    forms.alert("No loaded link found.", exitscript=True)


# ---------- UI ----------
xaml_str = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Copy Linked Elements"
        Width="420" Height="500"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize">
    <Window.Resources>
        <Style TargetType="TextBlock" x:Key="Header">
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Margin" Value="0,8,0,4"/>
            <Setter Property="Foreground" Value="#333"/>
        </Style>
    </Window.Resources>
    <Border Padding="16">
        <StackPanel>
            <TextBlock Text="COPY LINKED ELEMENTS" FontSize="15" FontWeight="Bold"
                       Foreground="#2C3E50" Margin="0,0,0,12"/>

            <TextBlock Text="1. Select the Link:" Style="{StaticResource Header}"/>
            <ComboBox x:Name="cb_links" Height="28" Margin="0,0,0,8"/>

            <TextBlock Text="2. Select the Category:" Style="{StaticResource Header}"/>
            <ListBox x:Name="lb_categories" Height="220" Margin="0,0,0,8"
                     SelectionMode="Extended"/>

            <TextBlock x:Name="tb_count" Text="0 categories found"
                       Foreground="#888" FontSize="11" Margin="0,0,0,12"/>

            <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
                <Button x:Name="btn_copy" Content="Copy" Width="100" Height="30"
                        IsEnabled="False" Margin="0,0,8,0"
                        Background="#2C3E50" Foreground="White" FontWeight="SemiBold"/>
                <Button x:Name="btn_cancel" Content="Cancel" Width="100" Height="30"/>
            </StackPanel>
        </StackPanel>
    </Border>
</Window>
"""


class CopyLinkedUI(object):
    def __init__(self):
        xaml_bytes = Encoding.UTF8.GetBytes(xaml_str)
        stream = MemoryStream(xaml_bytes)
        self.window = XamlReader.Load(stream)

        self.cb_links = self.window.FindName("cb_links")
        self.lb_categories = self.window.FindName("lb_categories")
        self.tb_count = self.window.FindName("tb_count")
        self.btn_copy = self.window.FindName("btn_copy")
        self.btn_cancel = self.window.FindName("btn_cancel")

        self.selected_link = None
        self.selected_cats = []

        for name in sorted(link_dict.keys()):
            self.cb_links.Items.Add(name)

        self.cb_links.SelectionChanged += self.on_link_changed
        self.lb_categories.SelectionChanged += self.on_cat_changed
        self.btn_copy.Click += self.on_copy
        self.btn_cancel.Click += self.on_cancel

    def on_link_changed(self, sender, args):
        self.lb_categories.Items.Clear()
        name = self.cb_links.SelectedItem
        if not name:
            return
        self.selected_link = link_dict[str(name)]
        link_doc = self.selected_link.GetLinkDocument()

        # Collect categories that actually have instances
        cats = {}
        for cat in link_doc.Settings.Categories:
            try:
                if cat and cat.Name:
                    count = (
                        FilteredElementCollector(link_doc)
                        .OfCategoryId(cat.Id)
                        .WhereElementIsNotElementType()
                        .GetElementCount()
                    )
                    if count > 0:
                        cats[cat.Name] = {"id": cat.Id, "count": count}
            except Exception:
                pass

        self.cat_dict = cats
        for c in sorted(cats.keys()):
            self.lb_categories.Items.Add(
                u"{} ({})".format(c, cats[c]["count"])
            )

        self.tb_count.Text = "{} categories with elements".format(len(cats))
        self.btn_copy.IsEnabled = False

    def on_cat_changed(self, sender, args):
        self.selected_cats = [
            item for item in self.lb_categories.SelectedItems
        ]
        self.btn_copy.IsEnabled = len(self.selected_cats) > 0

    def on_copy(self, sender, args):
        self.window.DialogResult = True
        self.window.Close()

    def on_cancel(self, sender, args):
        self.window.DialogResult = False
        self.window.Close()

    def show(self):
        return self.window.ShowDialog()


ui = CopyLinkedUI()
if not ui.show():
    script.exit()

# ---------- Copy ----------
link_instance = ui.selected_link
link_doc = link_instance.GetLinkDocument()
link_transform = link_instance.GetTotalTransform()
opts = CopyPasteOptions()
opts.SetDuplicateTypeNamesHandler(CopyHandler())

output = script.get_output()
total_copied = 0
errors = []

with revit.Transaction("Copy Linked Elements"):
    for display_name in ui.selected_cats:
        # Extract real category name (remove " (123)" count suffix)
        cat_name = display_name.rsplit(" (", 1)[0]
        if cat_name not in ui.cat_dict:
            continue
        cat_id = ui.cat_dict[cat_name]["id"]

        try:
            elem_ids = list(
                FilteredElementCollector(link_doc)
                .OfCategoryId(cat_id)
                .WhereElementIsNotElementType()
                .ToElementIds()
            )
            if not elem_ids:
                continue

            net_ids = NetList[ElementId]()
            for eid in elem_ids:
                net_ids.Add(eid)

            copied = ElementTransformUtils.CopyElements(
                link_doc, net_ids, doc, link_transform, opts,
            )
            count = copied.Count if copied else 0
            total_copied += count
            output.print_md("- **{}**: {} elements copied".format(
                cat_name, count))
        except Exception as ex:
            errors.append(u"{}: {}".format(cat_name, ex))
            output.print_md("- **{}**: ERROR - {}".format(cat_name, ex))

msg = u"{} elements copied.".format(total_copied)
if errors:
    msg += u"\n{} categories had errors.".format(len(errors))
forms.alert(msg, title="Copy Linked Elements")
