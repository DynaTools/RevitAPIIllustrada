# -*- coding: utf-8 -*-
"""Adds shared parameters as batch project parameters."""

__title__ = "Add Shared\nParameters"
__doc__ = (
    "Adds shared parameters as batch project parameters "
    "from a shared parameters .txt file.\n"
    "Select the parameters, categories, binding type and group."
)
__author__ = "Paulo Giavoni"

import clr
import os

clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows.Markup import XamlReader
import System
import System.Reflection
from System.Windows.Forms import OpenFileDialog
from System.Windows.Forms import DialogResult as WFDialogResult

from pyrevit import revit, forms, script, HOST_APP
from Autodesk.Revit.DB import (
    CategorySet,
    InstanceBinding,
    TypeBinding,
)

# Revit 2024+ removeu BuiltInParameterGroup em favor de ForgeTypeId
USE_FORGE = int(HOST_APP.version) >= 2024

if USE_FORGE:
    from Autodesk.Revit.DB import LabelUtils, ForgeTypeId
    try:
        from Autodesk.Revit.DB import GroupTypeId, ParameterUtils
    except ImportError:
        GroupTypeId = None
        ParameterUtils = None
else:
    from Autodesk.Revit.DB import BuiltInParameterGroup, LabelUtils

doc = revit.doc
app = doc.Application
uidoc = revit.uidoc
logger = script.get_logger()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_existing_param_names():
    """Returns names of parameters already bound to the project."""
    names = set()
    it = doc.ParameterBindings.ForwardIterator()
    while it.MoveNext():
        names.add(it.Key.Name)
    return names


def get_bindable_categories():
    """Returns categories that accept bound parameters."""
    result = {}
    for cat in doc.Settings.Categories:
        try:
            if cat and cat.Name and cat.AllowsBoundParameters:
                result[cat.Name] = cat
        except Exception:
            pass
    return result


def get_param_group_map():
    """Returns label → parameter group map (ForgeTypeId or BuiltInParameterGroup)."""
    mapping = {}
    if USE_FORGE:
        # Revit 2024+: usar ParameterUtils.GetAllBuiltInGroups()
        if ParameterUtils is not None:
            try:
                all_groups = ParameterUtils.GetAllBuiltInGroups()
                for ftid in all_groups:
                    try:
                        label = LabelUtils.GetLabelForGroup(ftid)
                        if label and label.strip():
                            mapping[label] = ftid
                    except Exception:
                        pass
            except Exception:
                pass
        # Fallback: reflection on GroupTypeId
        if not mapping and GroupTypeId is not None:
            gt = clr.GetClrType(GroupTypeId)
            for prop in gt.GetProperties(
                System.Reflection.BindingFlags.Static
                | System.Reflection.BindingFlags.Public
            ):
                try:
                    ftid = prop.GetValue(None)
                    if ftid is None:
                        continue
                    label = LabelUtils.GetLabelForGroup(ftid)
                    if label and label.strip():
                        mapping[label] = ftid
                except Exception:
                    pass
        # "Other" = ForgeTypeId vazio (equivalente a INVALID)
        if "Other" not in mapping:
            mapping["Other"] = ForgeTypeId("")
    else:
        for member in System.Enum.GetValues(clr.GetClrType(BuiltInParameterGroup)):
            try:
                label = LabelUtils.GetLabelFor(member)
                if label and label.strip():
                    mapping[label] = member
            except Exception:
                pass
    return mapping


# ---------------------------------------------------------------------------
# XAML
# ---------------------------------------------------------------------------

XAML_STR = u"""\
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Add Shared Parameters to Project"
    Width="950" Height="720"
    WindowStartupLocation="CenterScreen"
    ResizeMode="CanResizeWithGrip">
  <Grid Margin="15">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Row 0: File -->
    <GroupBox Grid.Row="0" Header="Shared Parameters File"
              Margin="0,0,0,8">
      <StackPanel Orientation="Horizontal" Margin="5">
        <TextBox x:Name="txt_filepath" Width="660" IsReadOnly="True"
                 VerticalContentAlignment="Center" Margin="0,0,5,0"/>
        <Button x:Name="btn_browse" Content="Browse..."
                Width="85" Height="28" Margin="0,0,5,0"/>
        <Button x:Name="btn_current" Content="Use Current"
                Width="85" Height="28"/>
      </StackPanel>
    </GroupBox>

    <!-- Row 1: Sub-headers + search + select-all -->
    <Grid Grid.Row="1">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>

      <StackPanel Grid.Column="0" Margin="0,0,5,2">
        <TextBlock Text="Parameters:" FontWeight="Bold"
                   FontSize="13" Margin="0,0,0,4"/>
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <TextBox x:Name="txt_search_params" Grid.Column="0"
                   Margin="0,0,5,0"/>
          <Button x:Name="btn_all_params" Grid.Column="1" Content="All"
                  Width="55" Height="24" Margin="0,0,3,0"/>
          <Button x:Name="btn_none_params" Grid.Column="2" Content="None"
                  Width="55" Height="24"/>
        </Grid>
      </StackPanel>

      <StackPanel Grid.Column="1" Margin="5,0,0,2">
        <TextBlock Text="Categories:" FontWeight="Bold"
                   FontSize="13" Margin="0,0,0,4"/>
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <TextBox x:Name="txt_search_cats" Grid.Column="0"
                   Margin="0,0,5,0"/>
          <Button x:Name="btn_all_cats" Grid.Column="1" Content="All"
                  Width="55" Height="24" Margin="0,0,3,0"/>
          <Button x:Name="btn_none_cats" Grid.Column="2" Content="None"
                  Width="55" Height="24"/>
        </Grid>
      </StackPanel>
    </Grid>

    <!-- Row 2: Lists -->
    <Grid Grid.Row="2" Margin="0,4,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <ListBox x:Name="lst_parameters" Grid.Column="0" Margin="0,0,5,0"
               SelectionMode="Extended"/>
      <ListBox x:Name="lst_categories" Grid.Column="1" Margin="5,0,0,0"
               SelectionMode="Extended"/>
    </Grid>

    <!-- Row 3: Status -->
    <StackPanel Grid.Row="3" Orientation="Horizontal" Margin="0,6,0,0">
      <TextBlock x:Name="txt_status_params"
                 Text="0 parameter(s) selected" Margin="0,0,30,0"/>
      <TextBlock x:Name="txt_status_cats"
                 Text="0 category(ies) selected"/>
    </StackPanel>

    <!-- Row 4: Options -->
    <GroupBox Grid.Row="4" Header="Options" Margin="0,8,0,8">
      <StackPanel Orientation="Horizontal" Margin="5">
        <TextBlock Text="Binding:" VerticalAlignment="Center"
                   Margin="0,0,8,0"/>
        <RadioButton x:Name="rb_instance" Content="Instance"
                     IsChecked="True" VerticalAlignment="Center"
                     Margin="0,0,18,0"/>
        <RadioButton x:Name="rb_type" Content="Type"
                     VerticalAlignment="Center"/>
        <TextBlock Text="Group:" VerticalAlignment="Center"
                   Margin="35,0,8,0"/>
        <ComboBox x:Name="cmb_param_group" Width="250"
                  VerticalAlignment="Center"/>
      </StackPanel>
    </GroupBox>

    <!-- Row 5: Execute -->
    <Button Grid.Row="5" x:Name="btn_execute"
            Content="Add Selected Parameters"
            Height="40" FontSize="14" FontWeight="Bold"/>
  </Grid>
</Window>"""


# ---------------------------------------------------------------------------
# Data wrappers
# ---------------------------------------------------------------------------

class ParamItem(object):
    """Represents a parameter from the shared parameter file."""
    def __init__(self, group_name, definition, already_exists=False):
        self.group_name = group_name
        self.definition = definition
        self.name = definition.Name
        try:
            ptype = str(definition.ParameterType)
        except Exception:
            ptype = ""
        self.display = u"[{}]  {}".format(group_name, definition.Name)
        if ptype and ptype != "Invalid":
            self.display += u"  ({})".format(ptype)
        if already_exists:
            self.display += u"  \u2714 already exists"
        self.already_exists = already_exists

    def __repr__(self):
        return self.display

    def __str__(self):
        return self.display


class CatItem(object):
    """Represents a Revit category."""
    def __init__(self, category):
        self.category = category
        self.name = category.Name

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class AddSharedParametersUI(object):
    def __init__(self):
        xaml_bytes = Encoding.UTF8.GetBytes(XAML_STR)
        stream = MemoryStream(xaml_bytes)
        self.window = XamlReader.Load(stream)
        stream.Close()

        # Controls
        self.txt_filepath      = self.window.FindName("txt_filepath")
        self.btn_browse        = self.window.FindName("btn_browse")
        self.btn_current       = self.window.FindName("btn_current")
        self.txt_search_params = self.window.FindName("txt_search_params")
        self.txt_search_cats   = self.window.FindName("txt_search_cats")
        self.btn_all_params    = self.window.FindName("btn_all_params")
        self.btn_none_params   = self.window.FindName("btn_none_params")
        self.btn_all_cats      = self.window.FindName("btn_all_cats")
        self.btn_none_cats     = self.window.FindName("btn_none_cats")
        self.lst_parameters    = self.window.FindName("lst_parameters")
        self.lst_categories    = self.window.FindName("lst_categories")
        self.rb_instance       = self.window.FindName("rb_instance")
        self.rb_type           = self.window.FindName("rb_type")
        self.cmb_param_group   = self.window.FindName("cmb_param_group")
        self.btn_execute       = self.window.FindName("btn_execute")
        self.txt_status_params = self.window.FindName("txt_status_params")
        self.txt_status_cats   = self.window.FindName("txt_status_cats")

        # State
        self.all_params = []
        self.all_cats   = []
        self.param_group_map = {}
        # display-string → data-object lookups
        self._param_map = {}   # display_str → ParamItem
        self._cat_map   = {}   # cat_name → CatItem

        # Wire events
        self.btn_browse.Click  += self.on_browse
        self.btn_current.Click += self.on_use_current
        self.btn_all_params.Click  += self.on_select_all_params
        self.btn_none_params.Click += self.on_select_none_params
        self.btn_all_cats.Click    += self.on_select_all_cats
        self.btn_none_cats.Click   += self.on_select_none_cats
        self.txt_search_params.TextChanged += self.on_search_params
        self.txt_search_cats.TextChanged   += self.on_search_cats
        self.lst_parameters.SelectionChanged += self.on_param_selection
        self.lst_categories.SelectionChanged += self.on_cat_selection
        self.btn_execute.Click += self.on_execute

        # Init data
        self._populate_categories()
        self._populate_param_groups()
        self._try_load_current_file()

    # -- initializers -------------------------------------------------------

    def _populate_categories(self):
        cats = get_bindable_categories()
        self.all_cats = sorted(
            [CatItem(c) for c in cats.values()], key=lambda x: x.name
        )
        self._cat_map = {ci.name: ci for ci in self.all_cats}
        self.lst_categories.Items.Clear()
        for item in self.all_cats:
            self.lst_categories.Items.Add(item.name)

    def _populate_param_groups(self):
        self.param_group_map = get_param_group_map()
        labels = sorted(self.param_group_map.keys())
        default_idx = 0
        default_label = "Data" if USE_FORGE else None
        for i, label in enumerate(labels):
            self.cmb_param_group.Items.Add(label)
            if USE_FORGE:
                if label == "Data" or label == "Dados":
                    default_idx = i
            else:
                if self.param_group_map[label] == BuiltInParameterGroup.PG_DATA:
                    default_idx = i
        if self.cmb_param_group.Items.Count > 0:
            self.cmb_param_group.SelectedIndex = default_idx

    def _try_load_current_file(self):
        try:
            path = app.SharedParametersFilename
            if path and os.path.exists(path):
                self.txt_filepath.Text = path
                self._load_params_from_file(path)
        except Exception:
            pass

    # -- shared param file loading ------------------------------------------

    def _load_params_from_file(self, filepath):
        original = None
        try:
            original = app.SharedParametersFilename
        except Exception:
            pass

        try:
            app.SharedParametersFilename = filepath
            sp_file = app.OpenSharedParameterFile()
            if not sp_file:
                forms.alert(
                    u"Could not open the shared parameters file.",
                    title="Error",
                )
                return

            existing = get_existing_param_names()
            self.all_params = []
            for group in sp_file.Groups:
                for defn in group.Definitions:
                    already = defn.Name in existing
                    item = ParamItem(group.Name, defn, already)
                    self.all_params.append(item)

            self.all_params.sort(key=lambda x: x.display.lower())
            self._param_map = {pi.display: pi for pi in self.all_params}
            self._refresh_param_list()
            self.txt_filepath.Text = filepath

        except Exception as ex:
            forms.alert(
                u"Error loading file:\n{}".format(ex), title="Error"
            )
        finally:
            if original and original != filepath:
                try:
                    app.SharedParametersFilename = original
                except Exception:
                    pass

    def _refresh_param_list(self):
        query = self.txt_search_params.Text.strip().lower()
        self.lst_parameters.Items.Clear()
        for item in self.all_params:
            if not query or query in item.display.lower():
                self.lst_parameters.Items.Add(item.display)

    def _refresh_cat_list(self):
        query = self.txt_search_cats.Text.strip().lower()
        self.lst_categories.Items.Clear()
        for item in self.all_cats:
            if not query or query in item.name.lower():
                self.lst_categories.Items.Add(item.name)

    # -- event handlers -----------------------------------------------------

    def on_browse(self, sender, args):
        dlg = OpenFileDialog()
        dlg.Filter = (
            "Shared Parameter Files (*.txt)|*.txt|All Files (*.*)|*.*"
        )
        dlg.Title = u"Select Shared Parameters File"
        if dlg.ShowDialog() == WFDialogResult.OK:
            self._load_params_from_file(dlg.FileName)

    def on_use_current(self, sender, args):
        try:
            path = app.SharedParametersFilename
        except Exception:
            path = None
        if path and os.path.exists(path):
            self._load_params_from_file(path)
        else:
            forms.alert(
                    u"No shared parameters file is configured in Revit.",
                    title="Warning",
                )

    def on_search_params(self, sender, args):
        self._refresh_param_list()

    def on_search_cats(self, sender, args):
        self._refresh_cat_list()

    def on_select_all_params(self, sender, args):
        self.lst_parameters.SelectAll()

    def on_select_none_params(self, sender, args):
        self.lst_parameters.UnselectAll()

    def on_select_all_cats(self, sender, args):
        self.lst_categories.SelectAll()

    def on_select_none_cats(self, sender, args):
        self.lst_categories.UnselectAll()

    def on_param_selection(self, sender, args):
        n = self.lst_parameters.SelectedItems.Count
        self.txt_status_params.Text = u"{} parameter(s) selected".format(n)

    def on_cat_selection(self, sender, args):
        n = self.lst_categories.SelectedItems.Count
        self.txt_status_cats.Text = u"{} category(ies) selected".format(n)

    # -- execute ------------------------------------------------------------

    def on_execute(self, sender, args):
        sel_param_strs = list(self.lst_parameters.SelectedItems)
        if not sel_param_strs:
            forms.alert(u"Select at least one parameter.", title="Warning")
            return
        sel_params = [self._param_map[s] for s in sel_param_strs if s in self._param_map]

        sel_cat_strs = list(self.lst_categories.SelectedItems)
        if not sel_cat_strs:
            forms.alert(u"Select at least one category.", title="Warning")
            return
        sel_cats = [self._cat_map[s] for s in sel_cat_strs if s in self._cat_map]

        if self.cmb_param_group.SelectedIndex < 0:
            forms.alert(u"Select a parameter group.", title="Warning")
            return

        filepath = self.txt_filepath.Text
        if not filepath or not os.path.exists(filepath):
            forms.alert(
                u"Parameter file not found.", title="Error"
            )
            return

        group_label = str(self.cmb_param_group.SelectedItem)
        param_group = self.param_group_map.get(group_label)
        if param_group is None:
            forms.alert(u"Invalid parameter group.", title="Error")
            return

        # Build category set
        cat_set = CategorySet()
        for ci in sel_cats:
            cat_set.Insert(ci.category)

        is_instance = self.rb_instance.IsChecked
        binding = (
            InstanceBinding(cat_set) if is_instance else TypeBinding(cat_set)
        )

        # Set shared param file and get fresh definitions
        original = None
        try:
            original = app.SharedParametersFilename
        except Exception:
            pass

        try:
            app.SharedParametersFilename = filepath
            sp_file = app.OpenSharedParameterFile()
            if not sp_file:
                forms.alert(
                    u"Could not open the file.", title="Error"
                )
                return

            # Build name → definition lookup
            defn_map = {}
            for grp in sp_file.Groups:
                for defn in grp.Definitions:
                    defn_map[defn.Name] = defn

            existing = get_existing_param_names()
            added = 0
            skipped = 0
            errors = []

            with revit.Transaction("Add Shared Parameters"):
                for pi in sel_params:
                    if pi.name in existing:
                        skipped += 1
                        continue
                    defn = defn_map.get(pi.name)
                    if not defn:
                        errors.append(
                            u"{}: definition not found".format(pi.name)
                        )
                        continue
                    try:
                        doc.ParameterBindings.Insert(
                            defn, binding, param_group
                        )
                        added += 1
                    except Exception as ex:
                        errors.append(u"{}: {}".format(pi.name, ex))

            msg = (
                u"Added: {}\n"
                u"Ignored (already exist): {}"
            ).format(added, skipped)
            if errors:
                msg += u"\n\nErrors ({}):\n{}".format(
                    len(errors), u"\n".join(errors)
                )
            forms.alert(msg, title="Result")
            self.window.Close()

        except Exception as ex:
            forms.alert(
                u"Error during execution:\n{}".format(ex), title="Error"
            )
        finally:
            if original:
                try:
                    app.SharedParametersFilename = original
                except Exception:
                    pass

    def show(self):
        self.window.ShowDialog()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

ui = AddSharedParametersUI()
ui.show()
