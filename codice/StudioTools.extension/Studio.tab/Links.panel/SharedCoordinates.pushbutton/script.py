# -*- coding: utf-8 -*-
"""Show host sites, internal origin and shared coordinates vs linked models."""

__title__ = "Shared\nCoordinates"
__doc__ = (
    "Lists all Sites (ProjectLocations) in the host model, shows the "
    "Internal origin comparison with linked models, and compares shared "
    "coordinate values. Export to CSV."
)
__author__ = "Paulo Giavoni"

import clr
import math

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    RevitLinkInstance,
    BasePoint,
    ProjectLocation,
    BuiltInParameter,
    XYZ,
    Transform,
    Transaction,
    UnitUtils,
)
from pyrevit import revit, forms, script

from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows import Visibility
from System.Windows.Markup import XamlReader

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

# ============================================================
# UNIT HELPERS
# ============================================================

FEET_TO_M = 0.3048
FEET_TO_MM = 304.8
RAD_TO_DEG = 180.0 / math.pi

try:
    from Autodesk.Revit.DB import UnitTypeId
    def _to_m(feet):
        return UnitUtils.ConvertFromInternalUnits(feet, UnitTypeId.Meters)
    def _to_mm(feet):
        return UnitUtils.ConvertFromInternalUnits(feet, UnitTypeId.Millimeters)
except Exception:
    def _to_m(feet):
        return feet * FEET_TO_M
    def _to_mm(feet):
        return feet * FEET_TO_MM


def _fmt_m(feet):
    return "{:.3f}".format(_to_m(feet))


def _fmt_mm(feet):
    return "{:.1f}".format(_to_mm(feet))


def _fmt_deg(rad):
    return "{:.4f}".format(rad * RAD_TO_DEG)


def _fmt_dms(rad):
    """Format radians as degrees minutes seconds."""
    deg_total = abs(rad * RAD_TO_DEG)
    d = int(deg_total)
    m = int((deg_total - d) * 60)
    s = (deg_total - d - m / 60.0) * 3600.0
    sign = "" if rad >= 0 else "-"
    return u"{}{}\u00b0 {:02d}' {:04.1f}\"".format(sign, d, m, s)


# ============================================================
# DATA COLLECTION
# ============================================================

def _get_all_sites(document):
    """Return list of all ProjectLocations (sites) with their data."""
    sites = []
    active_name = ""
    try:
        active_name = document.ActiveProjectLocation.Name
    except Exception:
        pass

    try:
        all_locs = FilteredElementCollector(document) \
            .OfClass(ProjectLocation) \
            .WhereElementIsNotElementType() \
            .ToElements()
    except Exception:
        all_locs = []

    for loc in all_locs:
        try:
            name = loc.Name
        except Exception:
            name = "?"
        try:
            pos = loc.GetProjectPosition(XYZ.Zero)
            ew = pos.EastWest
            ns = pos.NorthSouth
            elev = pos.Elevation
            angle = pos.Angle
        except Exception:
            ew = ns = elev = angle = 0.0

        sites.append({
            "name": name,
            "current": (name == active_name),
            "ew": ew,
            "ns": ns,
            "elev": elev,
            "angle": angle,
        })
    return sites


def _get_base_points(document):
    """Extract Survey Point and Project Base Point internal positions."""
    result = {"sp": None, "pbp": None}
    try:
        sp = BasePoint.GetSurveyPoint(document)
        result["sp"] = {"position": sp.Position, "shared": sp.SharedPosition}
    except Exception:
        pass
    try:
        pbp = BasePoint.GetProjectBasePoint(document)
        result["pbp"] = {"position": pbp.Position, "shared": pbp.SharedPosition}
    except Exception:
        pass

    # Read displayed parameter values
    for key, bp_obj in [("sp", result.get("sp")), ("pbp", result.get("pbp"))]:
        if bp_obj is None:
            continue
        try:
            elem = BasePoint.GetSurveyPoint(document) if key == "sp" \
                else BasePoint.GetProjectBasePoint(document)
            for suffix, bip in [
                ("ew", BuiltInParameter.BASEPOINT_EASTWEST_PARAM),
                ("ns", BuiltInParameter.BASEPOINT_NORTHSOUTH_PARAM),
                ("elev", BuiltInParameter.BASEPOINT_ELEVATION_PARAM),
                ("angle", BuiltInParameter.BASEPOINT_ANGLETON_PARAM),
            ]:
                p = elem.get_Parameter(bip)
                if p and p.HasValue:
                    bp_obj[suffix] = p.AsDouble()
                else:
                    bp_obj[suffix] = 0.0
        except Exception:
            bp_obj.setdefault("ew", 0.0)
            bp_obj.setdefault("ns", 0.0)
            bp_obj.setdefault("elev", 0.0)
            bp_obj.setdefault("angle", 0.0)

    return result


def _get_link_data(link_instance):
    """Get all coordinate data for a single link."""
    lt = link_instance.GetTotalTransform()
    is_identity = lt.AlmostEqual(Transform.Identity)
    offset_ft = math.sqrt(lt.Origin.X ** 2 + lt.Origin.Y ** 2 + lt.Origin.Z ** 2)
    rotation_rad = math.atan2(lt.BasisX.Y, lt.BasisX.X)

    link_doc = link_instance.GetLinkDocument()
    if link_doc is None:
        return None

    link_sites = _get_all_sites(link_doc)
    link_bp = _get_base_points(link_doc)

    return {
        "sites": link_sites,
        "base_points": link_bp,
        "transform": {
            "is_identity": is_identity,
            "offset_mm": _to_mm(offset_ft),
            "rotation_deg": rotation_rad * RAD_TO_DEG,
            "origin_x": lt.Origin.X,
            "origin_y": lt.Origin.Y,
            "origin_z": lt.Origin.Z,
        },
    }


def collect_all_data():
    """Collect all data for host and links."""
    host_sites = _get_all_sites(doc)
    host_bp = _get_base_points(doc)
    host_active = None
    for s in host_sites:
        if s["current"]:
            host_active = s
            break
    if host_active is None and host_sites:
        host_active = host_sites[0]

    host = {
        "name": doc.Title or "Host Model",
        "sites": host_sites,
        "base_points": host_bp,
        "active_site": host_active,
    }

    links = []
    for lnk in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        link_name = lnk.Name or "Unknown Link"
        link_doc = lnk.GetLinkDocument()

        if link_doc is None:
            links.append({"name": link_name, "loaded": False})
            continue

        ld = _get_link_data(lnk)
        if ld is None:
            links.append({"name": link_name, "loaded": False})
            continue

        # Find the link's active site
        link_active = None
        for s in ld["sites"]:
            if s["current"]:
                link_active = s
                break
        if link_active is None and ld["sites"]:
            link_active = ld["sites"][0]

        # Compare internal origins (transform)
        xf = ld["transform"]
        internal_match = xf["is_identity"]

        # Compare shared coordinates (active site values)
        shared_match = False
        diff_ew = diff_ns = diff_elev = diff_angle = 0.0
        if host_active and link_active:
            diff_ew = abs(host_active["ew"] - link_active["ew"])
            diff_ns = abs(host_active["ns"] - link_active["ns"])
            diff_elev = abs(host_active["elev"] - link_active["elev"])
            diff_angle = abs(host_active["angle"] - link_active["angle"])
            tol_ft = 0.001
            tol_angle = 0.0001
            shared_match = (
                diff_ew < tol_ft
                and diff_ns < tol_ft
                and diff_elev < tol_ft
                and diff_angle < tol_angle
            )

        links.append({
            "name": link_name,
            "loaded": True,
            "sites": ld["sites"],
            "base_points": ld["base_points"],
            "transform": xf,
            "active_site": link_active,
            "internal_match": internal_match,
            "shared_match": shared_match,
            "diff_ew": diff_ew,
            "diff_ns": diff_ns,
            "diff_elev": diff_elev,
            "diff_angle": diff_angle,
        })

    return host, links


# ============================================================
# XAML UI
# ============================================================

XAML_STR = u"""\
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Shared Coordinates Manager"
    Width="960" SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="CanResizeWithGrip"
    MaxHeight="900">
  <ScrollViewer VerticalScrollBarVisibility="Auto">
  <Grid Margin="15">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Host Model Sites -->
    <GroupBox Grid.Row="0" Header="Host Model - Sites (ProjectLocations)"
              Margin="0,0,0,10" FontWeight="Bold">
      <StackPanel Margin="8">
        <TextBlock x:Name="txt_host_name" FontWeight="Normal"
                   Margin="0,0,0,6"/>
        <DataGrid x:Name="dg_sites"
                  AutoGenerateColumns="False" IsReadOnly="True"
                  CanUserSortColumns="True"
                  HeadersVisibility="Column"
                  AlternatingRowBackground="#F0F4F8"
                  GridLinesVisibility="Horizontal"
                  BorderThickness="1" BorderBrush="#CCC"
                  MaxHeight="180"
                  FontWeight="Normal">
          <DataGrid.Columns>
            <DataGridTextColumn Header="Site Name"
                Binding="{Binding site_name}" Width="*" MinWidth="140"/>
            <DataGridTextColumn Header="Active"
                Binding="{Binding active}" Width="55"/>
            <DataGridTextColumn Header="E/W (m)"
                Binding="{Binding ew}" Width="80"/>
            <DataGridTextColumn Header="N/S (m)"
                Binding="{Binding ns}" Width="80"/>
            <DataGridTextColumn Header="Elev (m)"
                Binding="{Binding elev}" Width="80"/>
            <DataGridTextColumn Header="Angle (deg)"
                Binding="{Binding angle}" Width="80"/>
            <DataGridTextColumn Header="Angle (DMS)"
                Binding="{Binding angle_dms}" Width="100"/>
          </DataGrid.Columns>
        </DataGrid>
      </StackPanel>
    </GroupBox>

    <!-- Host Base Points -->
    <GroupBox Grid.Row="1" Header="Host Model - Base Points"
              Margin="0,0,0,10" FontWeight="Bold">
      <Grid Margin="8">
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="140"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <TextBlock Grid.Row="0" Grid.Column="0" Text="Survey Point:"
                   FontWeight="Normal" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="0" Grid.Column="1" x:Name="txt_host_sp"
                   FontWeight="Normal" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" Grid.Column="0" Text="Project Base Point:"
                   FontWeight="Normal" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" Grid.Column="1" x:Name="txt_host_pbp"
                   FontWeight="Normal" Margin="0,0,0,4"/>
      </Grid>
    </GroupBox>

    <!-- Links Comparison -->
    <GroupBox Grid.Row="2" Header="Linked Models - Comparison"
              Margin="0,0,0,10" FontWeight="Bold">
      <StackPanel Margin="8">
        <DataGrid x:Name="dg_links"
                  AutoGenerateColumns="False" IsReadOnly="True"
                  CanUserSortColumns="True"
                  CanUserResizeColumns="True"
                  HeadersVisibility="Column"
                  AlternatingRowBackground="#F0F4F8"
                  GridLinesVisibility="Horizontal"
                  BorderThickness="1" BorderBrush="#CCC"
                  MaxHeight="260"
                  FontWeight="Normal">
          <DataGrid.Columns>
            <DataGridTextColumn Header="Link Name"
                Binding="{Binding name}" Width="*" MinWidth="160"/>
            <DataGridTextColumn Header="Active Site"
                Binding="{Binding active_site}" Width="110"/>
            <DataGridTextColumn Header="Internal"
                Binding="{Binding internal_status}" Width="75"/>
            <DataGridTextColumn Header="Shared"
                Binding="{Binding shared_status}" Width="75"/>
            <DataGridTextColumn Header="Offset (mm)"
                Binding="{Binding offset}" Width="80"/>
            <DataGridTextColumn Header="Rot (deg)"
                Binding="{Binding rotation}" Width="70"/>
          </DataGrid.Columns>
        </DataGrid>
        <TextBlock x:Name="txt_no_links"
                   Text="No linked models found"
                   Foreground="#999" FontStyle="Italic" FontWeight="Normal"
                   Margin="0,6,0,0"/>
      </StackPanel>
    </GroupBox>

    <!-- Link Detail -->
    <GroupBox Grid.Row="3" Header="Selected Link - Detail"
              Margin="0,0,0,10" FontWeight="Bold"
              x:Name="grp_detail" Visibility="Collapsed">
      <StackPanel Margin="8">
        <TextBlock x:Name="txt_detail" FontWeight="Normal"
                   TextWrapping="Wrap"/>
        <TextBlock Text="Sites in this link:" FontWeight="SemiBold"
                   Margin="0,8,0,4"/>
        <DataGrid x:Name="dg_link_sites"
                  AutoGenerateColumns="False" IsReadOnly="True"
                  HeadersVisibility="Column"
                  AlternatingRowBackground="#F0F4F8"
                  GridLinesVisibility="Horizontal"
                  BorderThickness="1" BorderBrush="#CCC"
                  MaxHeight="140"
                  FontWeight="Normal">
          <DataGrid.Columns>
            <DataGridTextColumn Header="Site Name"
                Binding="{Binding site_name}" Width="*" MinWidth="140"/>
            <DataGridTextColumn Header="Active"
                Binding="{Binding active}" Width="55"/>
            <DataGridTextColumn Header="E/W (m)"
                Binding="{Binding ew}" Width="80"/>
            <DataGridTextColumn Header="N/S (m)"
                Binding="{Binding ns}" Width="80"/>
            <DataGridTextColumn Header="Elev (m)"
                Binding="{Binding elev}" Width="80"/>
            <DataGridTextColumn Header="Angle (deg)"
                Binding="{Binding angle}" Width="80"/>
            <DataGridTextColumn Header="Angle (DMS)"
                Binding="{Binding angle_dms}" Width="100"/>
          </DataGrid.Columns>
        </DataGrid>
      </StackPanel>
    </GroupBox>

    <!-- Summary -->
    <TextBlock Grid.Row="4" x:Name="txt_summary"
               Foreground="#555" FontSize="11"
               Margin="0,0,0,10"/>

    <!-- Buttons -->
    <StackPanel Grid.Row="5" Orientation="Horizontal"
                HorizontalAlignment="Right">
      <Button x:Name="btn_set_current" Content="Set Current"
              Width="100" Height="32" Margin="0,0,10,0" FontSize="12"
              Background="#8E44AD" Foreground="White" FontWeight="Bold"/>
      <Button x:Name="btn_delete_site" Content="Delete Site"
              Width="100" Height="32" Margin="0,0,10,0" FontSize="12"
              Background="#C0392B" Foreground="White" FontWeight="Bold"/>
      <Button x:Name="btn_copy_site" Content="Copy Site from Link"
              Width="140" Height="32" Margin="0,0,10,0" FontSize="12"
              Background="#27AE60" Foreground="White" FontWeight="Bold"/>
      <Button x:Name="btn_align" Content="Align to Link"
              Width="110" Height="32" Margin="0,0,10,0" FontSize="12"
              FontWeight="Bold" Background="#2980B9" Foreground="White"/>
      <Button x:Name="btn_export" Content="Export CSV"
              Width="90" Height="32" Margin="0,0,10,0" FontSize="12"/>
      <Button x:Name="btn_close" Content="Close"
              Width="90" Height="32" FontSize="12"/>
    </StackPanel>
  </Grid>
  </ScrollViewer>
</Window>"""


# ============================================================
# DATA ROWS
# ============================================================

class SiteRow(object):
    def __init__(self, site_dict):
        self.site_name = site_dict["name"]
        self.active = "Current" if site_dict["current"] else ""
        self.ew = _fmt_m(site_dict["ew"])
        self.ns = _fmt_m(site_dict["ns"])
        self.elev = _fmt_m(site_dict["elev"])
        self.angle = _fmt_deg(site_dict["angle"])
        self.angle_dms = _fmt_dms(site_dict["angle"])


class LinkRow(object):
    def __init__(self, link_data):
        self._data = link_data
        self.name = link_data["name"]

        if not link_data["loaded"]:
            self.active_site = "-"
            self.internal_status = "-"
            self.shared_status = "UNLOADED"
            self.offset = "-"
            self.rotation = "-"
            return

        asite = link_data.get("active_site")
        self.active_site = asite["name"] if asite else "?"
        self.internal_status = "MATCH" if link_data["internal_match"] else "OFFSET"
        self.shared_status = "MATCH" if link_data["shared_match"] else "DIFFER"
        self.offset = "{:.1f}".format(link_data["transform"]["offset_mm"])
        self.rotation = "{:.4f}".format(link_data["transform"]["rotation_deg"])


# ============================================================
# UI CLASS
# ============================================================

class SharedCoordinatesUI(object):
    def __init__(self):
        xaml_bytes = Encoding.UTF8.GetBytes(XAML_STR)
        stream = MemoryStream(xaml_bytes)
        self.window = XamlReader.Load(stream)
        stream.Close()

        self.txt_host_name = self.window.FindName("txt_host_name")
        self.dg_sites = self.window.FindName("dg_sites")
        self.txt_host_sp = self.window.FindName("txt_host_sp")
        self.txt_host_pbp = self.window.FindName("txt_host_pbp")
        self.dg_links = self.window.FindName("dg_links")
        self.txt_no_links = self.window.FindName("txt_no_links")
        self.grp_detail = self.window.FindName("grp_detail")
        self.txt_detail = self.window.FindName("txt_detail")
        self.dg_link_sites = self.window.FindName("dg_link_sites")
        self.txt_summary = self.window.FindName("txt_summary")
        self.btn_set_current = self.window.FindName("btn_set_current")
        self.btn_delete_site = self.window.FindName("btn_delete_site")
        self.btn_copy_site = self.window.FindName("btn_copy_site")
        self.btn_align = self.window.FindName("btn_align")
        self.btn_export = self.window.FindName("btn_export")
        self.btn_close = self.window.FindName("btn_close")

        self.btn_set_current.Click += self.on_set_current
        self.btn_delete_site.Click += self.on_delete_site
        self.btn_copy_site.Click += self.on_copy_site
        self.btn_align.Click += self.on_align
        self.btn_export.Click += self.on_export
        self.btn_close.Click += self.on_close
        self.dg_links.SelectionChanged += self.on_link_selected

        self.host_data = None
        self.links_data = []

        self._populate()

    def _format_bp(self, bp_info):
        """Format a base point dict as readable string."""
        if bp_info is None:
            return "Not available"
        pos = bp_info.get("position")
        if pos is None:
            return "Not available"
        return (
            u"Internal: ({}, {}, {}) m  |  "
            u"E/W: {} m  N/S: {} m  Elev: {} m  Angle: {}\u00b0"
        ).format(
            _fmt_m(pos.X), _fmt_m(pos.Y), _fmt_m(pos.Z),
            _fmt_m(bp_info.get("ew", 0)),
            _fmt_m(bp_info.get("ns", 0)),
            _fmt_m(bp_info.get("elev", 0)),
            _fmt_deg(bp_info.get("angle", 0)),
        )

    def _populate(self):
        self.host_data, self.links_data = collect_all_data()
        h = self.host_data

        # Host name
        self.txt_host_name.Text = "Model: {}".format(h["name"])

        # Host sites table
        site_rows = [SiteRow(s) for s in h["sites"]]
        self.dg_sites.ItemsSource = site_rows

        # Host base points
        bp = h["base_points"]
        self.txt_host_sp.Text = self._format_bp(bp.get("sp"))
        self.txt_host_pbp.Text = self._format_bp(bp.get("pbp"))

        # Links table
        link_rows = [LinkRow(ld) for ld in self.links_data]
        if link_rows:
            self.txt_no_links.Visibility = Visibility.Collapsed
            self.dg_links.ItemsSource = link_rows
        else:
            self.dg_links.Visibility = Visibility.Collapsed

        # Summary
        total = len(self.links_data)
        loaded = sum(1 for ld in self.links_data if ld["loaded"])
        int_ok = sum(1 for ld in self.links_data
                     if ld["loaded"] and ld.get("internal_match"))
        sh_ok = sum(1 for ld in self.links_data
                    if ld["loaded"] and ld.get("shared_match"))
        unloaded = total - loaded
        parts = ["{} links".format(total)]
        parts.append("{}/{} internal match".format(int_ok, loaded))
        parts.append("{}/{} shared match".format(sh_ok, loaded))
        if unloaded:
            parts.append("{} unloaded".format(unloaded))
        self.txt_summary.Text = "  |  ".join(parts)

    def on_link_selected(self, sender, args):
        idx = self.dg_links.SelectedIndex
        if idx < 0 or idx >= len(self.links_data):
            self.grp_detail.Visibility = Visibility.Collapsed
            return

        ld = self.links_data[idx]
        if not ld["loaded"]:
            self.grp_detail.Visibility = Visibility.Collapsed
            return

        self.grp_detail.Visibility = Visibility.Visible

        # Detail text
        xf = ld["transform"]
        bp = ld["base_points"]
        lines = []
        lines.append("Link: {}".format(ld["name"]))
        lines.append("")
        lines.append(
            u"Internal Origin: {} (offset {:.1f} mm, rotation {:.4f}\u00b0)".format(
                "MATCH" if ld["internal_match"] else "OFFSET",
                xf["offset_mm"], xf["rotation_deg"],
            )
        )
        lines.append(
            "  Transform origin: X={} Y={} Z={} m".format(
                _fmt_m(xf["origin_x"]), _fmt_m(xf["origin_y"]),
                _fmt_m(xf["origin_z"]),
            )
        )
        lines.append("")
        lines.append(
            "Shared Coordinates: {}".format(
                "MATCH" if ld["shared_match"] else "DIFFER"
            )
        )
        if not ld["shared_match"]:
            lines.append(
                u"  \u0394 E/W: {} mm  \u0394 N/S: {} mm  "
                u"\u0394 Elev: {} mm  \u0394 Angle: {}\u00b0".format(
                    _fmt_mm(ld["diff_ew"]), _fmt_mm(ld["diff_ns"]),
                    _fmt_mm(ld["diff_elev"]), _fmt_deg(ld["diff_angle"]),
                )
            )
        lines.append("")
        lines.append("Survey Point: {}".format(self._format_bp(bp.get("sp"))))
        lines.append("Project Base Point: {}".format(
            self._format_bp(bp.get("pbp"))
        ))

        self.txt_detail.Text = "\n".join(lines)

        # Link sites table
        link_site_rows = [SiteRow(s) for s in ld.get("sites", [])]
        self.dg_link_sites.ItemsSource = link_site_rows

    # ----------------------------------------------------------
    # Site management handlers
    # ----------------------------------------------------------

    def _get_host_locations(self):
        """Return list of ProjectLocation elements from the host."""
        return list(
            FilteredElementCollector(doc)
            .OfClass(ProjectLocation)
            .WhereElementIsNotElementType()
            .ToElements()
        )

    def on_set_current(self, sender, args):
        """Set a host site as the active ProjectLocation."""
        host_locs = self._get_host_locations()
        if not host_locs:
            forms.alert("No sites found.", title="Set Current")
            return

        active_name = ""
        try:
            active_name = doc.ActiveProjectLocation.Name
        except Exception:
            pass

        loc_labels = []
        for loc in host_locs:
            try:
                name = loc.Name
            except Exception:
                name = "?"
            tag = " (current)" if name == active_name else ""
            loc_labels.append("{}{}".format(name, tag))

        picked = forms.SelectFromList.show(
            loc_labels,
            title="Set Active Site",
            button_name="Set Current",
            multiselect=False,
        )
        if not picked:
            return

        idx = loc_labels.index(picked)
        chosen_loc = host_locs[idx]

        try:
            chosen_name = chosen_loc.Name
        except Exception:
            chosen_name = "?"

        if chosen_name == active_name:
            forms.alert(
                "'{}' is already the active site.".format(chosen_name),
                title="Set Current",
            )
            return

        t = Transaction(doc, "Set Active Site")
        t.Start()
        try:
            doc.ActiveProjectLocation = chosen_loc
            t.Commit()
        except Exception as e:
            t.RollBack()
            forms.alert(
                "Failed to set active site:\n{}".format(str(e)),
                title="Error",
            )
            return

        forms.alert(
            "Active site changed to '{}'.".format(chosen_name),
            title="Set Current",
        )
        self._populate()
        self.grp_detail.Visibility = Visibility.Collapsed

    def on_delete_site(self, sender, args):
        """Delete a host site (ProjectLocation)."""
        host_locs = self._get_host_locations()

        # Cannot delete Internal or Project, and need at least one left
        deletable = []
        deletable_labels = []
        active_name = ""
        try:
            active_name = doc.ActiveProjectLocation.Name
        except Exception:
            pass

        for loc in host_locs:
            try:
                name = loc.Name
            except Exception:
                name = "?"
            # Revit won't allow deleting "Internal" or the active location
            if name in ("Internal", "Project"):
                continue
            tag = " (current)" if name == active_name else ""
            deletable.append(loc)
            deletable_labels.append("{}{}".format(name, tag))

        if not deletable:
            forms.alert(
                "No deletable sites found.\n"
                "'Internal' and 'Project' cannot be deleted.",
                title="Delete Site",
            )
            return

        picked = forms.SelectFromList.show(
            deletable_labels,
            title="Delete Site",
            button_name="Delete",
            multiselect=False,
        )
        if not picked:
            return

        idx = deletable_labels.index(picked)
        loc_to_del = deletable[idx]
        try:
            del_name = loc_to_del.Name
        except Exception:
            del_name = "?"

        if del_name == active_name:
            forms.alert(
                "Cannot delete the active site '{}'.\n"
                "Set another site as current first.".format(del_name),
                title="Delete Site",
            )
            return

        if not forms.alert(
            "Delete site '{}'?\nThis cannot be undone.".format(del_name),
            title="Confirm Delete",
            yes=True, no=True,
        ):
            return

        t = Transaction(doc, "Delete Site")
        t.Start()
        try:
            doc.Delete(loc_to_del.Id)
            t.Commit()
        except Exception as e:
            t.RollBack()
            forms.alert(
                "Failed to delete site:\n{}".format(str(e)),
                title="Error",
            )
            return

        forms.alert("Site '{}' deleted.".format(del_name), title="Delete Site")
        self._populate()
        self.grp_detail.Visibility = Visibility.Collapsed

    def on_copy_site(self, sender, args):
        """Copy a site from a linked model into the host as a new site."""
        loaded = [ld for ld in self.links_data if ld["loaded"]]
        if not loaded:
            forms.alert("No loaded links available.", title="Copy Site")
            return

        # Pick source link
        link_names = [ld["name"] for ld in loaded]
        picked_link = forms.SelectFromList.show(
            link_names,
            title="Copy Site - Pick source link",
            button_name="Select",
            multiselect=False,
        )
        if not picked_link:
            return

        target = None
        for ld in loaded:
            if ld["name"] == picked_link:
                target = ld
                break
        if target is None:
            return

        target_sites = target.get("sites", [])
        if not target_sites:
            forms.alert("Link has no sites.", title="Copy Site")
            return

        # Pick source site
        if len(target_sites) == 1:
            source_site = target_sites[0]
        else:
            site_labels = []
            for s in target_sites:
                tag = " (current)" if s["current"] else ""
                site_labels.append("{}{}".format(s["name"], tag))
            picked_site = forms.SelectFromList.show(
                site_labels,
                title="Copy Site - Pick site to copy",
                button_name="Select",
                multiselect=False,
            )
            if not picked_site:
                return
            idx = site_labels.index(picked_site)
            source_site = target_sites[idx]

        new_name = source_site["name"]

        # Check if already exists in host
        host_locs = self._get_host_locations()
        existing_names = []
        for loc in host_locs:
            try:
                existing_names.append(loc.Name)
            except Exception:
                pass

        if new_name in existing_names:
            forms.alert(
                "Site '{}' already exists in the host model.\n"
                "Use 'Align to Link' to update its values.".format(new_name),
                title="Copy Site",
            )
            return

        if not forms.alert(
            "Create new site '{}' in host with:\n\n"
            "E/W: {} m\n"
            "N/S: {} m\n"
            "Elev: {} m\n"
            "Angle: {}".format(
                new_name,
                _fmt_m(source_site["ew"]), _fmt_m(source_site["ns"]),
                _fmt_m(source_site["elev"]), _fmt_deg(source_site["angle"]),
            ),
            title="Confirm Copy Site",
            yes=True, no=True,
        ):
            return

        t = Transaction(doc, "Copy Site from Link")
        t.Start()
        try:
            # Duplicate the active location, then rename and set values
            active_loc = doc.ActiveProjectLocation
            new_loc = active_loc.Duplicate(new_name)

            new_pos = doc.Application.Create.NewProjectPosition(
                source_site["ew"], source_site["ns"],
                source_site["elev"], source_site["angle"],
            )
            new_loc.SetProjectPosition(XYZ.Zero, new_pos)
            t.Commit()
        except Exception as e:
            t.RollBack()
            forms.alert(
                "Failed to create site:\n{}".format(str(e)),
                title="Error",
            )
            return

        forms.alert(
            "Site '{}' created in host.".format(new_name),
            title="Copy Site",
        )
        self._populate()
        self.grp_detail.Visibility = Visibility.Collapsed

    def on_align(self, sender, args):
        """Copy shared coordinates from a selected link to the host."""
        # Build list of loaded links
        loaded = [ld for ld in self.links_data if ld["loaded"]]
        if not loaded:
            forms.alert("No loaded links available.", title="Align")
            return

        # Let user pick which link to align to
        link_names = [ld["name"] for ld in loaded]
        picked = forms.SelectFromList.show(
            link_names,
            title="Align to Link",
            button_name="Select",
            multiselect=False,
        )
        if not picked:
            return

        # Find the selected link data
        target = None
        for ld in loaded:
            if ld["name"] == picked:
                target = ld
                break
        if target is None:
            return

        target_sites = target.get("sites", [])
        if not target_sites:
            forms.alert(
                "Selected link has no site data.",
                title="Align",
            )
            return

        # Let user pick which site from the link to use
        if len(target_sites) == 1:
            source_site = target_sites[0]
        else:
            site_labels = []
            for s in target_sites:
                tag = " (current)" if s["current"] else ""
                site_labels.append("{}{}".format(s["name"], tag))
            picked_site = forms.SelectFromList.show(
                site_labels,
                title="Pick source site from link",
                button_name="Select",
                multiselect=False,
            )
            if not picked_site:
                return
            idx = site_labels.index(picked_site)
            source_site = target_sites[idx]

        source_ew = source_site["ew"]
        source_ns = source_site["ns"]
        source_elev = source_site["elev"]
        source_angle = source_site["angle"]

        # Find or pick host ProjectLocation to update
        host_locs = FilteredElementCollector(doc) \
            .OfClass(ProjectLocation) \
            .WhereElementIsNotElementType() \
            .ToElements()

        # Try to find a host location matching the source site name
        target_loc = None
        for loc in host_locs:
            try:
                if loc.Name == source_site["name"]:
                    target_loc = loc
                    break
            except Exception:
                pass

        if target_loc is None:
            # Let user pick which host site to update
            loc_names = []
            for loc in host_locs:
                try:
                    loc_names.append(loc.Name)
                except Exception:
                    loc_names.append("?")
            picked_loc = forms.SelectFromList.show(
                loc_names,
                title="Pick host site to update",
                button_name="Select",
                multiselect=False,
            )
            if not picked_loc:
                return
            for loc in host_locs:
                try:
                    if loc.Name == picked_loc:
                        target_loc = loc
                        break
                except Exception:
                    pass

        if target_loc is None:
            forms.alert("Could not find host site.", title="Align")
            return

        # Confirm
        msg = (
            "Update host site '{}' with coordinates from\n"
            "link '{}' site '{}'?\n\n"
            "E/W: {} m\n"
            "N/S: {} m\n"
            "Elev: {} m\n"
            "Angle: {}\u00b0"
        ).format(
            target_loc.Name, target["name"], source_site["name"],
            _fmt_m(source_ew), _fmt_m(source_ns),
            _fmt_m(source_elev), _fmt_deg(source_angle),
        )
        if not forms.alert(msg, title="Confirm Align", yes=True, no=True):
            return

        # Apply
        t = Transaction(doc, "Align Shared Coordinates")
        t.Start()
        try:
            new_pos = doc.Application.Create.NewProjectPosition(
                source_ew, source_ns, source_elev, source_angle
            )
            target_loc.SetProjectPosition(XYZ.Zero, new_pos)
            t.Commit()
        except Exception as e:
            t.RollBack()
            forms.alert(
                "Failed to update coordinates:\n{}".format(str(e)),
                title="Error",
            )
            return

        forms.alert(
            "Host site '{}' updated successfully.\n"
            "Refreshing data...".format(target_loc.Name),
            title="Align Complete",
        )

        # Refresh UI
        self._populate()
        self.grp_detail.Visibility = Visibility.Collapsed

    def on_export(self, sender, args):
        filepath = forms.save_file(file_ext="csv")
        if not filepath:
            return

        lines = []
        lines.append(
            "Source,Type,Site,E/W (m),N/S (m),Elev (m),"
            "Angle (deg),Internal,Shared,Offset (mm)"
        )

        # Host sites
        for s in self.host_data["sites"]:
            tag = "(current)" if s["current"] else ""
            lines.append(u"{},Site,{} {},{},,,,,,".format(
                self.host_data["name"], s["name"], tag,
                "{},{},{},{}".format(
                    _fmt_m(s["ew"]), _fmt_m(s["ns"]),
                    _fmt_m(s["elev"]), _fmt_deg(s["angle"]),
                ),
            ))

        # Host base points
        bp = self.host_data["base_points"]
        for key, label in [("sp", "Survey Point"), ("pbp", "Project Base Point")]:
            b = bp.get(key)
            if b:
                lines.append(u"{},{},{},{},{},{},{},,,,".format(
                    self.host_data["name"], label, "",
                    _fmt_m(b.get("ew", 0)), _fmt_m(b.get("ns", 0)),
                    _fmt_m(b.get("elev", 0)), _fmt_deg(b.get("angle", 0)),
                ))

        # Links
        for ld in self.links_data:
            if not ld["loaded"]:
                lines.append(u"{},,,,,,,,,UNLOADED,".format(ld["name"]))
                continue

            xf = ld["transform"]
            asite = ld.get("active_site")
            asite_name = asite["name"] if asite else "?"

            # Link active site
            if asite:
                lines.append(u"{},Active Site,{},{},{},{},{},{},{},{}".format(
                    ld["name"], asite_name,
                    _fmt_m(asite["ew"]), _fmt_m(asite["ns"]),
                    _fmt_m(asite["elev"]), _fmt_deg(asite["angle"]),
                    "MATCH" if ld["internal_match"] else "OFFSET",
                    "MATCH" if ld["shared_match"] else "DIFFER",
                    "{:.1f}".format(xf["offset_mm"]),
                ))

            # All link sites
            for s in ld.get("sites", []):
                tag = "(current)" if s["current"] else ""
                lines.append(u"{},Site,{} {},{},,,,,,".format(
                    ld["name"], s["name"], tag,
                    "{},{},{},{}".format(
                        _fmt_m(s["ew"]), _fmt_m(s["ns"]),
                        _fmt_m(s["elev"]), _fmt_deg(s["angle"]),
                    ),
                ))

        with open(filepath, "w") as f:
            f.write("\n".join(lines))

        forms.alert(
            "Exported {} lines to:\n{}".format(len(lines), filepath),
            title="Export Complete",
        )

    def on_close(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()


# ============================================================
# ENTRY POINT
# ============================================================

ui = SharedCoordinatesUI()
ui.show()
