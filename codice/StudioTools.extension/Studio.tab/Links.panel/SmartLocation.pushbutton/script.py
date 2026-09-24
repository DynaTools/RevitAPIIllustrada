# -*- coding: utf-8 -*-
__title__ = "Smart\nLocation"
__doc__ = (
    "Select a link, import its Rooms and locate each element of the local "
    "model inside the link's Rooms.\n\n"
    "The result is written to the elements' parameter."
)
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
    BuiltInCategory,
    BuiltInParameter,
    SpatialElement,
    XYZ,
    UV,
    BoundingBoxXYZ,
    Transform,
    ElementId,
    Transaction,
    StorageType,
    CategorySet,
    InstanceBinding,
    ExternalDefinitionCreationOptions,
)
from Autodesk.Revit.DB.Architecture import Room

import os
import tempfile

from pyrevit import revit, forms, script

from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows.Markup import XamlReader
from System.Windows import Visibility

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()


# ─────────── UNIT HELPERS ───────────
try:
    from Autodesk.Revit.DB import UnitTypeId, UnitUtils, ForgeTypeId

    def _ft_to_m(feet):
        return UnitUtils.ConvertFromInternalUnits(feet, UnitTypeId.Meters)
except Exception:
    def _ft_to_m(feet):
        return feet * 0.3048


def _id_int(eid):
    """Numeric value of an ElementId on any Revit version.

    ``ElementId.IntegerValue`` was removed in Revit 2026 and ``Value``
    only exists from Revit 2024 on, so both spellings must be tried.
    """
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


# ─────────── COLLECT LINKS ───────────
_all_links = (
    FilteredElementCollector(doc)
    .OfClass(RevitLinkInstance)
    .ToElements()
)

if not _all_links:
    forms.alert("No Revit Link found in the project.", exitscript=True)

_link_dict = {}
for lnk in _all_links:
    link_doc = lnk.GetLinkDocument()
    if link_doc:
        name = link_doc.Title
        _link_dict[name] = lnk

if not _link_dict:
    forms.alert("No loaded link found.", exitscript=True)


# ─────────── ROOM EXTRACTION FROM LINK ───────────
def get_rooms_from_link(link_instance):
    """Extract rooms from linked document with their transformed geometry."""
    link_doc = link_instance.GetLinkDocument()
    if not link_doc:
        return []

    transform = link_instance.GetTotalTransform()

    rooms_data = []
    collector = (
        FilteredElementCollector(link_doc)
        .OfCategory(BuiltInCategory.OST_Rooms)
        .ToElements()
    )

    for room in collector:
        if room is None:
            continue
        # Skip unplaced or unbounded rooms
        try:
            if room.Area < 0.1:
                continue
            if room.Location is None:
                continue
        except Exception:
            continue

        room_name = room.get_Parameter(
            BuiltInParameter.ROOM_NAME
        )
        room_number = room.get_Parameter(
            BuiltInParameter.ROOM_NUMBER
        )
        room_level = room.get_Parameter(
            BuiltInParameter.ROOM_LEVEL_ID
        )

        name_val = room_name.AsString() if room_name else "?"
        number_val = room_number.AsString() if room_number else "?"

        # Get level name
        level_name = ""
        if room_level:
            try:
                lvl_id = room_level.AsElementId()
                lvl_elem = link_doc.GetElement(lvl_id)
                if lvl_elem:
                    level_name = lvl_elem.Name
            except Exception:
                pass

        # Get room point (location) and transform to host coordinates
        loc_pt = room.Location.Point
        transformed_pt = transform.OfPoint(loc_pt)

        # Get bounding box and transform
        bb = room.get_BoundingBox(None)
        if bb is None:
            continue

        bb_min = transform.OfPoint(bb.Min)
        bb_max = transform.OfPoint(bb.Max)

        rooms_data.append({
            "room": room,
            "link_doc": link_doc,
            "transform": transform,
            "name": name_val,
            "number": number_val,
            "level": level_name,
            "center": transformed_pt,
            "bb_min": bb_min,
            "bb_max": bb_max,
        })

    return rooms_data


def point_in_room_bb(point, room_data, tolerance=0.5):
    """Check if a point falls within the room's transformed bounding box
    with a vertical tolerance (feet)."""
    bb_min = room_data["bb_min"]
    bb_max = room_data["bb_max"]

    return (
        bb_min.X <= point.X <= bb_max.X
        and bb_min.Y <= point.Y <= bb_max.Y
        and (bb_min.Z - tolerance) <= point.Z <= (bb_max.Z + tolerance)
    )


def point_in_room_precise(point, room_data):
    """Use the Revit Room.IsPointInRoom API by inverse-transforming
    the host point back into link coordinate space."""
    room = room_data["room"]
    inv_transform = room_data["transform"].Inverse

    # Transform host-point back to link space
    link_point = inv_transform.OfPoint(point)

    try:
        return room.IsPointInRoom(link_point)
    except Exception:
        return False


def get_element_location_point(element):
    """Extract a representative point from an element."""
    loc = element.Location
    if loc is None:
        # fallback to bounding-box center
        bb = element.get_BoundingBox(None)
        if bb:
            return XYZ(
                (bb.Min.X + bb.Max.X) / 2.0,
                (bb.Min.Y + bb.Max.Y) / 2.0,
                (bb.Min.Z + bb.Max.Z) / 2.0,
            )
        return None

    # LocationPoint
    try:
        return loc.Point
    except Exception:
        pass

    # LocationCurve – use midpoint
    try:
        crv = loc.Curve
        return crv.Evaluate(0.5, True)
    except Exception:
        pass

    # Fallback to bounding box
    bb = element.get_BoundingBox(None)
    if bb:
        return XYZ(
            (bb.Min.X + bb.Max.X) / 2.0,
            (bb.Min.Y + bb.Max.Y) / 2.0,
            (bb.Min.Z + bb.Max.Z) / 2.0,
        )
    return None


# ─────────── SPATIAL LOOKUP ───────────
def find_room_for_element(element, rooms_data):
    """Find which linked room contains an element.
    Uses a two-pass approach:
      1. Bounding-box quick filter
      2. Precise IsPointInRoom on survivors
    Returns a dict with room info or None.
    """
    pt = get_element_location_point(element)
    if pt is None:
        return None

    # Pass 1 – bounding box pre-filter (fast)
    candidates = [r for r in rooms_data if point_in_room_bb(pt, r)]

    if not candidates:
        # try again with bigger tolerance for MEP above ceiling
        candidates = [r for r in rooms_data if point_in_room_bb(pt, r, tolerance=3.0)]

    # Pass 2 – precise check
    for room_data in candidates:
        if point_in_room_precise(pt, room_data):
            return room_data

    # If precise check failed but we had BB candidates, return best BB match
    if candidates:
        # sort by distance to room center
        def _dist(rd):
            c = rd["center"]
            return (
                (pt.X - c.X) ** 2
                + (pt.Y - c.Y) ** 2
                + (pt.Z - c.Z) ** 2
            )
        candidates.sort(key=_dist)
        return candidates[0]

    return None


# ─────────── CATEGORY LISTS ───────────
_MEP_CATEGORIES = [
    BuiltInCategory.OST_DuctCurves,
    BuiltInCategory.OST_DuctFitting,
    BuiltInCategory.OST_DuctAccessory,
    BuiltInCategory.OST_DuctTerminal,
    BuiltInCategory.OST_FlexDuctCurves,
    BuiltInCategory.OST_PipeCurves,
    BuiltInCategory.OST_PipeFitting,
    BuiltInCategory.OST_PipeAccessory,
    BuiltInCategory.OST_FlexPipeCurves,
    BuiltInCategory.OST_Sprinklers,
    BuiltInCategory.OST_CableTray,
    BuiltInCategory.OST_CableTrayFitting,
    BuiltInCategory.OST_Conduit,
    BuiltInCategory.OST_ConduitFitting,
    BuiltInCategory.OST_MechanicalEquipment,
    BuiltInCategory.OST_PlumbingFixtures,
    BuiltInCategory.OST_ElectricalEquipment,
    BuiltInCategory.OST_ElectricalFixtures,
    BuiltInCategory.OST_LightingFixtures,
    BuiltInCategory.OST_LightingDevices,
    BuiltInCategory.OST_FireAlarmDevices,
    BuiltInCategory.OST_DataDevices,
    BuiltInCategory.OST_CommunicationDevices,
    BuiltInCategory.OST_SecurityDevices,
]

_ARCH_CATEGORIES = [
    BuiltInCategory.OST_Doors,
    BuiltInCategory.OST_Windows,
    BuiltInCategory.OST_Furniture,
    BuiltInCategory.OST_FurnitureSystems,
    BuiltInCategory.OST_GenericModel,
    BuiltInCategory.OST_SpecialityEquipment,
    BuiltInCategory.OST_Casework,
]

_ALL_CATEGORIES = _MEP_CATEGORIES + _ARCH_CATEGORIES


def get_category_label(bic):
    """Friendly category label from BuiltInCategory enum."""
    try:
        cat = doc.Settings.Categories.get_Item(bic)
        if cat:
            return cat.Name
    except Exception:
        pass
    return str(bic).replace("OST_", "")


# ─────────── PARAMETER CREATION & WRITING ───────────
PARAM_NAME = "SL_Room"
_param_ensured = False


def _ensure_param_exists(categories_to_bind):
    """Create the 'Room' shared parameter on the given categories if missing.
    Uses a temporary shared-parameter file so as not to pollute the user's."""
    global _param_ensured
    if _param_ensured:
        return

    # Check if param already exists on at least one category
    sample = None
    for bic in categories_to_bind:
        try:
            elems = (
                FilteredElementCollector(doc)
                .OfCategory(bic)
                .WhereElementIsNotElementType()
                .FirstElement()
            )
            if elems:
                sample = elems
                break
        except Exception:
            pass

    if sample:
        p = sample.LookupParameter(PARAM_NAME)
        if p:
            _param_ensured = True
            return

    # Build a CategorySet for binding
    cat_set = CategorySet()
    for bic in categories_to_bind:
        try:
            cat = doc.Settings.Categories.get_Item(bic)
            if cat and cat.AllowsBoundParameters:
                cat_set.Insert(cat)
        except Exception:
            pass

    if cat_set.Size == 0:
        return

    # Save current shared-param file path and create a temp one
    app = doc.Application
    original_spf = app.SharedParametersFilename
    tmp_path = os.path.join(tempfile.gettempdir(), "_SmartLocation_sp.txt")

    try:
        # Create temp shared-param file
        with open(tmp_path, "w") as f:
            f.write("")
        app.SharedParametersFilename = tmp_path
        sp_file = app.OpenSharedParameterFile()

        # Create or get group
        group = sp_file.Groups.get_Item("SmartLocation")
        if group is None:
            group = sp_file.Groups.Create("SmartLocation")

        # Create definition
        defn = group.Definitions.get_Item(PARAM_NAME)
        if defn is None:
            try:
                # Revit 2023+
                from Autodesk.Revit.DB import SpecTypeId
                opts = ExternalDefinitionCreationOptions(PARAM_NAME, SpecTypeId.String.Text)
            except Exception:
                # Revit 2021 and older
                from Autodesk.Revit.DB import ParameterType as _PT
                opts = ExternalDefinitionCreationOptions(PARAM_NAME, _PT.Text)
            opts.Visible = True
            defn = group.Definitions.Create(opts)

        # Bind as instance parameter
        binding = app.Create.NewInstanceBinding(cat_set)
        binding_map = doc.ParameterBindings
        binding_map.Insert(defn, binding)

        _param_ensured = True
    except Exception as ex:
        print("Warning: could not create parameter '{}': {}".format(PARAM_NAME, ex))
    finally:
        # Restore original shared-param file
        try:
            app.SharedParametersFilename = original_spf or ""
        except Exception:
            pass
        # Clean up temp file
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def write_location_to_element(element, room_data):
    """Write combined room number + name into a single 'Room' parameter.
    Example value: '1.01 - Reception'"""
    value = u"{} - {}".format(room_data["number"], room_data["name"])
    try:
        p = element.LookupParameter(PARAM_NAME)
        if p and not p.IsReadOnly and p.StorageType == StorageType.String:
            p.Set(value)
            return True
    except Exception:
        pass
    return False


# ─────────── RESULT ROW ───────────
class ResultRow(object):
    """Bindable row for the results DataGrid."""
    def __init__(self, elem_id, elem_name, category, room_num, room_name, level, status):
        self.ElementId = str(elem_id)
        self.ElementName = elem_name
        self.Category = category
        self.RoomNumber = room_num
        self.RoomName = room_name
        self.Level = level
        self.Status = status


# ─────────── UI ───────────
_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="UNIBIM Smart Location – Room Detection from Link"
        Width="900" Height="700"
        WindowStartupLocation="CenterScreen"
        ResizeMode="CanResize">
    <Window.Resources>
        <Style TargetType="TextBlock" x:Key="Header">
            <Setter Property="FontSize" Value="13"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Margin" Value="0,8,0,4"/>
            <Setter Property="Foreground" Value="#333"/>
        </Style>
    </Window.Resources>
    <Grid Margin="14">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Title -->
        <TextBlock Grid.Row="0" Text="SMART LOCATION" FontSize="16"
                   FontWeight="Bold" Foreground="#2C3E50" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" TextWrapping="Wrap" Foreground="#666"
                   Text="Select a link to import its Rooms and locate elements from the current model."/>

        <!-- Link selection -->
        <StackPanel Grid.Row="2" Margin="0,10,0,0">
            <TextBlock Text="1 – Select the Link:" Style="{StaticResource Header}"/>
            <ComboBox x:Name="cb_links" Height="28" Margin="0,0,0,4"/>
            <TextBlock x:Name="tb_rooms_info" Text="" Foreground="#888" FontSize="11"/>
        </StackPanel>

        <!-- Category selection -->
        <StackPanel Grid.Row="3" Margin="0,8,0,0">
            <TextBlock Text="2 – Categories to process:" Style="{StaticResource Header}"/>
            <WrapPanel Margin="0,2,0,0">
                <CheckBox x:Name="chk_mep" Content="MEP" IsChecked="True" Margin="0,0,14,0"/>
                <CheckBox x:Name="chk_arch" Content="Architecture" IsChecked="False" Margin="0,0,14,0"/>
                <CheckBox x:Name="chk_selection" Content="Current selection only" IsChecked="False"/>
            </WrapPanel>
        </StackPanel>

        <!-- Results DataGrid -->
        <DataGrid Grid.Row="4" x:Name="dg_results"
                  AutoGenerateColumns="False"
                  IsReadOnly="True"
                  CanUserSortColumns="True"
                  Margin="0,10,0,0"
                  HeadersVisibility="Column"
                  GridLinesVisibility="Horizontal"
                  AlternatingRowBackground="#F8F8F8">
            <DataGrid.Columns>
                <DataGridTextColumn Header="Element ID" Binding="{Binding ElementId}" Width="80"/>
                <DataGridTextColumn Header="Element" Binding="{Binding ElementName}" Width="180"/>
                <DataGridTextColumn Header="Category" Binding="{Binding Category}" Width="130"/>
                <DataGridTextColumn Header="Room #" Binding="{Binding RoomNumber}" Width="80"/>
                <DataGridTextColumn Header="Room Name" Binding="{Binding RoomName}" Width="150"/>
                <DataGridTextColumn Header="Level" Binding="{Binding Level}" Width="100"/>
                <DataGridTextColumn Header="Status" Binding="{Binding Status}" Width="90"/>
            </DataGrid.Columns>
        </DataGrid>

        <!-- Stats -->
        <TextBlock Grid.Row="5" x:Name="tb_stats" Text="" Foreground="#444"
                   FontSize="11" Margin="0,6,0,0"/>

        <!-- Buttons -->
        <StackPanel Grid.Row="6" Orientation="Horizontal"
                    HorizontalAlignment="Right" Margin="0,10,0,0">
            <Button x:Name="btn_detect" Content="Detect" Width="110" Height="32"
                    Background="#2C3E50" Foreground="White" FontWeight="SemiBold"
                    Margin="0,0,8,0"/>
            <Button x:Name="btn_write" Content="Write" Width="110" Height="32"
                    Background="#27AE60" Foreground="White" FontWeight="SemiBold"
                    IsEnabled="False" Margin="0,0,8,0"/>
            <Button x:Name="btn_export" Content="Export CSV" Width="110" Height="32"
                    IsEnabled="False" Margin="0,0,8,0"/>
            <Button x:Name="btn_close" Content="Close" Width="90" Height="32"/>
        </StackPanel>
    </Grid>
</Window>
"""


class SmartLocationUI(object):
    def __init__(self):
        stream = MemoryStream(Encoding.UTF8.GetBytes(_XAML))
        self.window = XamlReader.Load(stream)

        # controls
        self.cb_links = self.window.FindName("cb_links")
        self.tb_rooms_info = self.window.FindName("tb_rooms_info")
        self.chk_mep = self.window.FindName("chk_mep")
        self.chk_arch = self.window.FindName("chk_arch")
        self.chk_selection = self.window.FindName("chk_selection")
        self.dg_results = self.window.FindName("dg_results")
        self.tb_stats = self.window.FindName("tb_stats")
        self.btn_detect = self.window.FindName("btn_detect")
        self.btn_write = self.window.FindName("btn_write")
        self.btn_export = self.window.FindName("btn_export")
        self.btn_close = self.window.FindName("btn_close")

        # populate
        for name in sorted(_link_dict.keys()):
            self.cb_links.Items.Add(name)

        # state
        self._rooms_data = []
        self._results = []  # list of ResultRow
        self._location_map = {}  # element_id -> room_data

        # events
        self.cb_links.SelectionChanged += self._on_link_changed
        self.btn_detect.Click += self._on_detect
        self.btn_write.Click += self._on_write
        self.btn_export.Click += self._on_export
        self.btn_close.Click += self._on_close

    # --- events ---
    def _on_link_changed(self, sender, args):
        name = self.cb_links.SelectedItem
        if not name:
            return
        link_inst = _link_dict[str(name)]
        self._rooms_data = get_rooms_from_link(link_inst)
        count = len(self._rooms_data)
        self.tb_rooms_info.Text = "{} Rooms found in link.".format(count)
        if count == 0:
            forms.alert(
                "The selected link has no valid Rooms (placed/bounded).",
                title="Smart Location",
            )

    def _collect_elements(self):
        """Collect host elements to process based on UI checkboxes."""
        if self.chk_selection.IsChecked:
            sel_ids = uidoc.Selection.GetElementIds()
            return [doc.GetElement(eid) for eid in sel_ids if doc.GetElement(eid)]

        cats = []
        if self.chk_mep.IsChecked:
            cats.extend(_MEP_CATEGORIES)
        if self.chk_arch.IsChecked:
            cats.extend(_ARCH_CATEGORIES)

        if not cats:
            forms.alert("Select at least one category.", title="Smart Location")
            return []

        elements = []
        for bic in cats:
            try:
                elems = (
                    FilteredElementCollector(doc)
                    .OfCategory(bic)
                    .WhereElementIsNotElementType()
                    .ToElements()
                )
                elements.extend(elems)
            except Exception:
                pass
        return elements

    def _on_detect(self, sender, args):
        if not self._rooms_data:
            forms.alert(
                "Select a link with Rooms before detecting.",
                title="Smart Location",
            )
            return

        elements = self._collect_elements()
        if not elements:
            forms.alert(
                "No elements found to process.",
                title="Smart Location",
            )
            return

        self._results = []
        self._location_map = {}
        found = 0
        not_found = 0

        import time
        t0 = time.time()

        for elem in elements:
            try:
                cat_name = elem.Category.Name if elem.Category else "?"
                elem_name = elem.Name or "?"
                eid = _id_int(elem.Id)

                room = find_room_for_element(elem, self._rooms_data)
                if room:
                    row = ResultRow(
                        eid, elem_name, cat_name,
                        room["number"], room["name"], room["level"],
                        "Found",
                    )
                    self._location_map[str(eid)] = room
                    found += 1
                else:
                    row = ResultRow(
                        eid, elem_name, cat_name,
                        "-", "-", "-", "Not found",
                    )
                    not_found += 1
                self._results.append(row)
            except Exception as ex:
                pass

        elapsed = time.time() - t0
        speed = len(elements) / elapsed if elapsed > 0 else 0

        self.dg_results.ItemsSource = self._results
        total_label = "{total} elements | {ok} located | {nf} no room | " \
                       "{t:.1f}s ({spd:.0f} elem/s)"
        self.tb_stats.Text = total_label.format(
            total=len(elements), ok=found, nf=not_found,
            t=elapsed, spd=speed,
        )

        self.btn_write.IsEnabled = found > 0
        self.btn_export.IsEnabled = len(self._results) > 0

    def _on_write(self, sender, args):
        if not self._location_map:
            return

        # Determine which categories need the parameter
        cats = []
        if self.chk_mep.IsChecked:
            cats.extend(_MEP_CATEGORIES)
        if self.chk_arch.IsChecked:
            cats.extend(_ARCH_CATEGORIES)
        if self.chk_selection.IsChecked:
            cats = _ALL_CATEGORIES
        if not cats:
            cats = _ALL_CATEGORIES

        written = 0
        skipped = 0

        with revit.Transaction("Smart Location – Write Room"):
            # Create parameter if it doesn't exist yet
            _ensure_param_exists(cats)

            for eid_str, room_data in self._location_map.items():
                try:
                    int_id = int(eid_str)
                    elem = doc.GetElement(ElementId(int_id))
                    if elem is None:
                        skipped += 1
                        continue
                    ok = write_location_to_element(elem, room_data)
                    if ok:
                        written += 1
                    else:
                        skipped += 1
                except Exception:
                    skipped += 1

        forms.alert(
            u"Write completed!\n\n"
            u"  Written: {}\n  Skipped: {}\n\n"
            u"Parameter: '{}'".format(
                written, skipped, PARAM_NAME,
            ),
            title="Smart Location",
        )

    def _on_export(self, sender, args):
        if not self._results:
            return
        filepath = forms.save_file(file_ext="csv")
        if not filepath:
            return

        lines = [
            "ElementId;Element;Category;RoomNumber;RoomName;Level;Status"
        ]
        for r in self._results:
            lines.append(
                u"{};{};{};{};{};{};{}".format(
                    r.ElementId, r.ElementName, r.Category,
                    r.RoomNumber, r.RoomName, r.Level, r.Status,
                )
            )
        with open(filepath, "w") as f:
            f.write("\n".join(lines))
        forms.alert("CSV exportado:\n{}".format(filepath), title="Smart Location")

    def _on_close(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()


# ─────────── ENTRY POINT ───────────
ui = SmartLocationUI()
ui.show()
