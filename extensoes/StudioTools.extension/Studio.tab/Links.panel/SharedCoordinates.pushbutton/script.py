# -*- coding: utf-8 -*-
"""Sites do hospedeiro, origem interna e coordenadas compartilhadas vs. links."""

__title__ = "Shared\nCoordinates"
__doc__ = (
    "Lista todos os sites (ProjectLocations) do modelo hospedeiro, mostra a "
    "comparação da origem interna com os modelos vinculados e compara os "
    "valores das coordenadas compartilhadas. Exporta para CSV."
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
# AUXILIARES DE UNIDADE
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
    """Formata radianos como graus, minutos e segundos."""
    deg_total = abs(rad * RAD_TO_DEG)
    d = int(deg_total)
    m = int((deg_total - d) * 60)
    s = (deg_total - d - m / 60.0) * 3600.0
    sign = "" if rad >= 0 else "-"
    return u"{}{}\u00b0 {:02d}' {:04.1f}\"".format(sign, d, m, s)


# ============================================================
# COLETA DE DADOS
# ============================================================

def _get_all_sites(document):
    """Retorna a lista de todos os ProjectLocations (sites), com os seus dados."""
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
    """Extrai as posições internas do ponto de levantamento e do ponto base do projeto."""
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

    # Lê os valores exibidos nos parâmetros
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
    """Obtém todos os dados de coordenadas de um único link."""
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
    """Coleta todos os dados do hospedeiro e dos links."""
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
        "name": doc.Title or "Modelo hospedeiro",
        "sites": host_sites,
        "base_points": host_bp,
        "active_site": host_active,
    }

    links = []
    for lnk in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        link_name = lnk.Name or "Link desconhecido"
        link_doc = lnk.GetLinkDocument()

        if link_doc is None:
            links.append({"name": link_name, "loaded": False})
            continue

        ld = _get_link_data(lnk)
        if ld is None:
            links.append({"name": link_name, "loaded": False})
            continue

        # Encontra o site ativo do link
        link_active = None
        for s in ld["sites"]:
            if s["current"]:
                link_active = s
                break
        if link_active is None and ld["sites"]:
            link_active = ld["sites"][0]

        # Compara as origens internas (transformação)
        xf = ld["transform"]
        internal_match = xf["is_identity"]

        # Compara as coordenadas compartilhadas (valores do site ativo)
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
# INTERFACE XAML
# ============================================================

XAML_STR = u"""\
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Shared Coordinates – gerenciador de coordenadas"
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

    <!-- Sites do modelo hospedeiro -->
    <GroupBox Grid.Row="0" Header="Modelo hospedeiro - Sites (ProjectLocations)"
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
            <DataGridTextColumn Header="Nome do site"
                Binding="{Binding site_name}" Width="*" MinWidth="140"/>
            <DataGridTextColumn Header="Ativo"
                Binding="{Binding active}" Width="55"/>
            <DataGridTextColumn Header="L/O (m)"
                Binding="{Binding ew}" Width="80"/>
            <DataGridTextColumn Header="N/S (m)"
                Binding="{Binding ns}" Width="80"/>
            <DataGridTextColumn Header="Elev. (m)"
                Binding="{Binding elev}" Width="80"/>
            <DataGridTextColumn Header="Ângulo (°)"
                Binding="{Binding angle}" Width="80"/>
            <DataGridTextColumn Header="Ângulo (GMS)"
                Binding="{Binding angle_dms}" Width="100"/>
          </DataGrid.Columns>
        </DataGrid>
      </StackPanel>
    </GroupBox>

    <!-- Pontos base do hospedeiro -->
    <GroupBox Grid.Row="1" Header="Modelo hospedeiro - Pontos base"
              Margin="0,0,0,10" FontWeight="Bold">
      <Grid Margin="8">
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="180"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <TextBlock Grid.Row="0" Grid.Column="0" Text="Ponto de levantamento:"
                   FontWeight="Normal" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="0" Grid.Column="1" x:Name="txt_host_sp"
                   FontWeight="Normal" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" Grid.Column="0" Text="Ponto base do projeto:"
                   FontWeight="Normal" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" Grid.Column="1" x:Name="txt_host_pbp"
                   FontWeight="Normal" Margin="0,0,0,4"/>
      </Grid>
    </GroupBox>

    <!-- Comparação dos links -->
    <GroupBox Grid.Row="2" Header="Modelos vinculados - Comparação"
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
            <DataGridTextColumn Header="Nome do link"
                Binding="{Binding name}" Width="*" MinWidth="160"/>
            <DataGridTextColumn Header="Site ativo"
                Binding="{Binding active_site}" Width="110"/>
            <DataGridTextColumn Header="Origem int."
                Binding="{Binding internal_status}" Width="95"/>
            <DataGridTextColumn Header="Compartilhadas"
                Binding="{Binding shared_status}" Width="110"/>
            <DataGridTextColumn Header="Desloc. (mm)"
                Binding="{Binding offset}" Width="90"/>
            <DataGridTextColumn Header="Rot. (°)"
                Binding="{Binding rotation}" Width="70"/>
          </DataGrid.Columns>
        </DataGrid>
        <TextBlock x:Name="txt_no_links"
                   Text="Nenhum modelo vinculado encontrado"
                   Foreground="#999" FontStyle="Italic" FontWeight="Normal"
                   Margin="0,6,0,0"/>
      </StackPanel>
    </GroupBox>

    <!-- Detalhe do link -->
    <GroupBox Grid.Row="3" Header="Link selecionado - Detalhe"
              Margin="0,0,0,10" FontWeight="Bold"
              x:Name="grp_detail" Visibility="Collapsed">
      <StackPanel Margin="8">
        <TextBlock x:Name="txt_detail" FontWeight="Normal"
                   TextWrapping="Wrap"/>
        <TextBlock Text="Sites deste link:" FontWeight="SemiBold"
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
            <DataGridTextColumn Header="Nome do site"
                Binding="{Binding site_name}" Width="*" MinWidth="140"/>
            <DataGridTextColumn Header="Ativo"
                Binding="{Binding active}" Width="55"/>
            <DataGridTextColumn Header="L/O (m)"
                Binding="{Binding ew}" Width="80"/>
            <DataGridTextColumn Header="N/S (m)"
                Binding="{Binding ns}" Width="80"/>
            <DataGridTextColumn Header="Elev. (m)"
                Binding="{Binding elev}" Width="80"/>
            <DataGridTextColumn Header="Ângulo (°)"
                Binding="{Binding angle}" Width="80"/>
            <DataGridTextColumn Header="Ângulo (GMS)"
                Binding="{Binding angle_dms}" Width="100"/>
          </DataGrid.Columns>
        </DataGrid>
      </StackPanel>
    </GroupBox>

    <!-- Resumo -->
    <TextBlock Grid.Row="4" x:Name="txt_summary"
               Foreground="#555" FontSize="11"
               Margin="0,0,0,10"/>

    <!-- Botões -->
    <StackPanel Grid.Row="5" Orientation="Horizontal"
                HorizontalAlignment="Right">
      <Button x:Name="btn_set_current" Content="Tornar atual"
              Width="100" Height="32" Margin="0,0,10,0" FontSize="12"
              Background="#8E44AD" Foreground="White" FontWeight="Bold"/>
      <Button x:Name="btn_delete_site" Content="Excluir site"
              Width="100" Height="32" Margin="0,0,10,0" FontSize="12"
              Background="#C0392B" Foreground="White" FontWeight="Bold"/>
      <Button x:Name="btn_copy_site" Content="Copiar site do link"
              Width="140" Height="32" Margin="0,0,10,0" FontSize="12"
              Background="#27AE60" Foreground="White" FontWeight="Bold"/>
      <Button x:Name="btn_align" Content="Alinhar ao link"
              Width="120" Height="32" Margin="0,0,10,0" FontSize="12"
              FontWeight="Bold" Background="#2980B9" Foreground="White"/>
      <Button x:Name="btn_export" Content="Exportar CSV"
              Width="100" Height="32" Margin="0,0,10,0" FontSize="12"/>
      <Button x:Name="btn_close" Content="Fechar"
              Width="90" Height="32" FontSize="12"/>
    </StackPanel>
  </Grid>
  </ScrollViewer>
</Window>"""


# ============================================================
# LINHAS DE DADOS
# ============================================================

class SiteRow(object):
    def __init__(self, site_dict):
        self.site_name = site_dict["name"]
        self.active = "Sim" if site_dict["current"] else ""
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
            self.shared_status = "DESCARREGADO"
            self.offset = "-"
            self.rotation = "-"
            return

        asite = link_data.get("active_site")
        self.active_site = asite["name"] if asite else "?"
        self.internal_status = "IGUAL" if link_data["internal_match"] else "DESLOCADA"
        self.shared_status = "IGUAL" if link_data["shared_match"] else "DIFERENTE"
        self.offset = "{:.1f}".format(link_data["transform"]["offset_mm"])
        self.rotation = "{:.4f}".format(link_data["transform"]["rotation_deg"])


# ============================================================
# CLASSE DA INTERFACE
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
        """Formata o dict de um ponto base como texto legível."""
        if bp_info is None:
            return u"Não disponível"
        pos = bp_info.get("position")
        if pos is None:
            return u"Não disponível"
        return (
            u"Posição interna: ({}, {}, {}) m  |  "
            u"L/O: {} m  N/S: {} m  Elev.: {} m  Ângulo: {}\u00b0"
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

        # Nome do hospedeiro
        self.txt_host_name.Text = "Modelo: {}".format(h["name"])

        # Tabela dos sites do hospedeiro
        site_rows = [SiteRow(s) for s in h["sites"]]
        self.dg_sites.ItemsSource = site_rows

        # Pontos base do hospedeiro
        bp = h["base_points"]
        self.txt_host_sp.Text = self._format_bp(bp.get("sp"))
        self.txt_host_pbp.Text = self._format_bp(bp.get("pbp"))

        # Tabela dos links
        link_rows = [LinkRow(ld) for ld in self.links_data]
        if link_rows:
            self.txt_no_links.Visibility = Visibility.Collapsed
            self.dg_links.ItemsSource = link_rows
        else:
            self.dg_links.Visibility = Visibility.Collapsed

        # Resumo
        total = len(self.links_data)
        loaded = sum(1 for ld in self.links_data if ld["loaded"])
        int_ok = sum(1 for ld in self.links_data
                     if ld["loaded"] and ld.get("internal_match"))
        sh_ok = sum(1 for ld in self.links_data
                    if ld["loaded"] and ld.get("shared_match"))
        unloaded = total - loaded
        parts = ["{} links".format(total)]
        parts.append("{}/{} com origem interna igual".format(int_ok, loaded))
        parts.append("{}/{} com coordenadas compartilhadas iguais".format(sh_ok, loaded))
        if unloaded:
            parts.append("{} descarregados".format(unloaded))
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

        # Texto do detalhe
        xf = ld["transform"]
        bp = ld["base_points"]
        lines = []
        lines.append("Link: {}".format(ld["name"]))
        lines.append("")
        lines.append(
            u"Origem interna: {} (deslocamento {:.1f} mm, rotação {:.4f}\u00b0)".format(
                "IGUAL" if ld["internal_match"] else "DESLOCADA",
                xf["offset_mm"], xf["rotation_deg"],
            )
        )
        lines.append(
            u"  Origem da transformação: X={} Y={} Z={} m".format(
                _fmt_m(xf["origin_x"]), _fmt_m(xf["origin_y"]),
                _fmt_m(xf["origin_z"]),
            )
        )
        lines.append("")
        lines.append(
            "Coordenadas compartilhadas: {}".format(
                "IGUAL" if ld["shared_match"] else "DIFERENTE"
            )
        )
        if not ld["shared_match"]:
            lines.append(
                u"  \u0394 L/O: {} mm  \u0394 N/S: {} mm  "
                u"\u0394 Elev.: {} mm  \u0394 Ângulo: {}\u00b0".format(
                    _fmt_mm(ld["diff_ew"]), _fmt_mm(ld["diff_ns"]),
                    _fmt_mm(ld["diff_elev"]), _fmt_deg(ld["diff_angle"]),
                )
            )
        lines.append("")
        lines.append("Ponto de levantamento: {}".format(self._format_bp(bp.get("sp"))))
        lines.append("Ponto base do projeto: {}".format(
            self._format_bp(bp.get("pbp"))
        ))

        self.txt_detail.Text = "\n".join(lines)

        # Tabela dos sites do link
        link_site_rows = [SiteRow(s) for s in ld.get("sites", [])]
        self.dg_link_sites.ItemsSource = link_site_rows

    # ----------------------------------------------------------
    # Handlers de gerenciamento dos sites
    # ----------------------------------------------------------

    def _get_host_locations(self):
        """Retorna a lista dos elementos ProjectLocation do hospedeiro."""
        return list(
            FilteredElementCollector(doc)
            .OfClass(ProjectLocation)
            .WhereElementIsNotElementType()
            .ToElements()
        )

    def on_set_current(self, sender, args):
        """Define um site do hospedeiro como o ProjectLocation ativo."""
        host_locs = self._get_host_locations()
        if not host_locs:
            forms.alert("Nenhum site encontrado.", title="Tornar atual")
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
            tag = " (atual)" if name == active_name else ""
            loc_labels.append("{}{}".format(name, tag))

        picked = forms.SelectFromList.show(
            loc_labels,
            title="Definir site ativo",
            button_name="Tornar atual",
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
                u"'{}' já é o site ativo.".format(chosen_name),
                title="Tornar atual",
            )
            return

        t = Transaction(doc, "Definir site ativo")
        t.Start()
        try:
            doc.ActiveProjectLocation = chosen_loc
            t.Commit()
        except Exception as e:
            t.RollBack()
            forms.alert(
                "Falha ao definir o site ativo:\n{}".format(str(e)),
                title="Erro",
            )
            return

        forms.alert(
            "Site ativo alterado para '{}'.".format(chosen_name),
            title="Tornar atual",
        )
        self._populate()
        self.grp_detail.Visibility = Visibility.Collapsed

    def on_delete_site(self, sender, args):
        """Exclui um site do hospedeiro (ProjectLocation)."""
        host_locs = self._get_host_locations()

        # Internal e Project não podem ser excluídos, e precisa sobrar ao menos um
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
            # O Revit não permite excluir "Internal" nem o local ativo
            if name in ("Internal", "Project"):
                continue
            tag = " (atual)" if name == active_name else ""
            deletable.append(loc)
            deletable_labels.append("{}{}".format(name, tag))

        if not deletable:
            forms.alert(
                u"Nenhum site que possa ser excluído foi encontrado.\n"
                u"'Internal' e 'Project' não podem ser excluídos.",
                title="Excluir site",
            )
            return

        picked = forms.SelectFromList.show(
            deletable_labels,
            title="Excluir site",
            button_name="Excluir",
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
                u"Não é possível excluir o site ativo '{}'.\n"
                u"Torne outro site atual primeiro.".format(del_name),
                title="Excluir site",
            )
            return

        if not forms.alert(
            u"Excluir o site '{}'?\nIsto não pode ser desfeito.".format(del_name),
            title=u"Confirmar exclusão",
            yes=True, no=True,
        ):
            return

        t = Transaction(doc, "Excluir site")
        t.Start()
        try:
            doc.Delete(loc_to_del.Id)
            t.Commit()
        except Exception as e:
            t.RollBack()
            forms.alert(
                "Falha ao excluir o site:\n{}".format(str(e)),
                title="Erro",
            )
            return

        forms.alert(u"Site '{}' excluído.".format(del_name), title="Excluir site")
        self._populate()
        self.grp_detail.Visibility = Visibility.Collapsed

    def on_copy_site(self, sender, args):
        """Copia um site de um modelo vinculado para o hospedeiro, como um site novo."""
        loaded = [ld for ld in self.links_data if ld["loaded"]]
        if not loaded:
            forms.alert(u"Nenhum link carregado disponível.", title="Copiar site")
            return

        # Escolhe o link de origem
        link_names = [ld["name"] for ld in loaded]
        picked_link = forms.SelectFromList.show(
            link_names,
            title="Copiar site - Escolha o link de origem",
            button_name="Selecionar",
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
            forms.alert(u"O link não tem sites.", title="Copiar site")
            return

        # Escolhe o site de origem
        if len(target_sites) == 1:
            source_site = target_sites[0]
        else:
            site_labels = []
            for s in target_sites:
                tag = " (atual)" if s["current"] else ""
                site_labels.append("{}{}".format(s["name"], tag))
            picked_site = forms.SelectFromList.show(
                site_labels,
                title="Copiar site - Escolha o site a copiar",
                button_name="Selecionar",
                multiselect=False,
            )
            if not picked_site:
                return
            idx = site_labels.index(picked_site)
            source_site = target_sites[idx]

        new_name = source_site["name"]

        # Verifica se já existe no hospedeiro
        host_locs = self._get_host_locations()
        existing_names = []
        for loc in host_locs:
            try:
                existing_names.append(loc.Name)
            except Exception:
                pass

        if new_name in existing_names:
            forms.alert(
                u"O site '{}' já existe no modelo hospedeiro.\n"
                u"Use 'Alinhar ao link' para atualizar os seus valores.".format(new_name),
                title="Copiar site",
            )
            return

        if not forms.alert(
            "Criar o site novo '{}' no hospedeiro com:\n\n"
            "L/O: {} m\n"
            "N/S: {} m\n"
            "Elev.: {} m\n"
            u"Ângulo: {}".format(
                new_name,
                _fmt_m(source_site["ew"]), _fmt_m(source_site["ns"]),
                _fmt_m(source_site["elev"]), _fmt_deg(source_site["angle"]),
            ),
            title=u"Confirmar cópia do site",
            yes=True, no=True,
        ):
            return

        t = Transaction(doc, "Copiar site do link")
        t.Start()
        try:
            # Duplica o local ativo, depois dá o nome e define os valores
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
                "Falha ao criar o site:\n{}".format(str(e)),
                title="Erro",
            )
            return

        forms.alert(
            "Site '{}' criado no hospedeiro.".format(new_name),
            title="Copiar site",
        )
        self._populate()
        self.grp_detail.Visibility = Visibility.Collapsed

    def on_align(self, sender, args):
        """Copia as coordenadas compartilhadas de um link selecionado para o hospedeiro."""
        # Monta a lista dos links carregados
        loaded = [ld for ld in self.links_data if ld["loaded"]]
        if not loaded:
            forms.alert(u"Nenhum link carregado disponível.", title="Alinhar")
            return

        # O usuário escolhe a qual link alinhar
        link_names = [ld["name"] for ld in loaded]
        picked = forms.SelectFromList.show(
            link_names,
            title="Alinhar ao link",
            button_name="Selecionar",
            multiselect=False,
        )
        if not picked:
            return

        # Encontra os dados do link selecionado
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
                u"O link selecionado não tem dados de site.",
                title="Alinhar",
            )
            return

        # O usuário escolhe qual site do link usar
        if len(target_sites) == 1:
            source_site = target_sites[0]
        else:
            site_labels = []
            for s in target_sites:
                tag = " (atual)" if s["current"] else ""
                site_labels.append("{}{}".format(s["name"], tag))
            picked_site = forms.SelectFromList.show(
                site_labels,
                title="Escolha o site de origem no link",
                button_name="Selecionar",
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

        # Encontra ou escolhe o ProjectLocation do hospedeiro a atualizar
        host_locs = FilteredElementCollector(doc) \
            .OfClass(ProjectLocation) \
            .WhereElementIsNotElementType() \
            .ToElements()

        # Tenta achar um local do hospedeiro com o mesmo nome do site de origem
        target_loc = None
        for loc in host_locs:
            try:
                if loc.Name == source_site["name"]:
                    target_loc = loc
                    break
            except Exception:
                pass

        if target_loc is None:
            # O usuário escolhe qual site do hospedeiro atualizar
            loc_names = []
            for loc in host_locs:
                try:
                    loc_names.append(loc.Name)
                except Exception:
                    loc_names.append("?")
            picked_loc = forms.SelectFromList.show(
                loc_names,
                title="Escolha o site do hospedeiro a atualizar",
                button_name="Selecionar",
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
            forms.alert(u"Não foi possível encontrar o site do hospedeiro.", title="Alinhar")
            return

        # Confirmação
        msg = (
            "Atualizar o site '{}' do hospedeiro com as coordenadas do\n"
            "link '{}', site '{}'?\n\n"
            "L/O: {} m\n"
            "N/S: {} m\n"
            "Elev.: {} m\n"
            u"Ângulo: {}\u00b0"
        ).format(
            target_loc.Name, target["name"], source_site["name"],
            _fmt_m(source_ew), _fmt_m(source_ns),
            _fmt_m(source_elev), _fmt_deg(source_angle),
        )
        if not forms.alert(msg, title="Confirmar alinhamento", yes=True, no=True):
            return

        # Aplica
        t = Transaction(doc, "Alinhar coordenadas compartilhadas")
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
                "Falha ao atualizar as coordenadas:\n{}".format(str(e)),
                title="Erro",
            )
            return

        forms.alert(
            "Site '{}' do hospedeiro atualizado com sucesso.\n"
            "Atualizando os dados...".format(target_loc.Name),
            title=u"Alinhamento concluído",
        )

        # Atualiza a interface
        self._populate()
        self.grp_detail.Visibility = Visibility.Collapsed

    def on_export(self, sender, args):
        filepath = forms.save_file(file_ext="csv")
        if not filepath:
            return

        lines = []
        lines.append(
            "Modelo,Tipo,Site,L/O (m),N/S (m),Elev. (m),"
            u"Ângulo (graus),Origem interna,Compartilhadas,Deslocamento (mm)"
        )

        # Sites do hospedeiro
        for s in self.host_data["sites"]:
            tag = "(atual)" if s["current"] else ""
            lines.append(u"{},Site,{} {},{},,,,,,".format(
                self.host_data["name"], s["name"], tag,
                "{},{},{},{}".format(
                    _fmt_m(s["ew"]), _fmt_m(s["ns"]),
                    _fmt_m(s["elev"]), _fmt_deg(s["angle"]),
                ),
            ))

        # Pontos base do hospedeiro
        bp = self.host_data["base_points"]
        for key, label in [("sp", "Ponto de levantamento"), ("pbp", "Ponto base do projeto")]:
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
                lines.append(u"{},,,,,,,,,DESCARREGADO,".format(ld["name"]))
                continue

            xf = ld["transform"]
            asite = ld.get("active_site")
            asite_name = asite["name"] if asite else "?"

            # Site ativo do link
            if asite:
                lines.append(u"{},Site ativo,{},{},{},{},{},{},{},{}".format(
                    ld["name"], asite_name,
                    _fmt_m(asite["ew"]), _fmt_m(asite["ns"]),
                    _fmt_m(asite["elev"]), _fmt_deg(asite["angle"]),
                    "IGUAL" if ld["internal_match"] else "DESLOCADA",
                    "IGUAL" if ld["shared_match"] else "DIFERENTE",
                    "{:.1f}".format(xf["offset_mm"]),
                ))

            # Todos os sites do link
            for s in ld.get("sites", []):
                tag = "(atual)" if s["current"] else ""
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
            "{} linhas exportadas para:\n{}".format(len(lines), filepath),
            title=u"Exportação concluída",
        )

    def on_close(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()


# ============================================================
# PONTO DE ENTRADA
# ============================================================

ui = SharedCoordinatesUI()
ui.show()
