# -*- coding: utf-8 -*-
"""Compara os níveis entre o modelo hospedeiro e os modelos vinculados."""

__title__ = "Compare\nLevels"
__doc__ = (
    "Compara nomes e cotas dos níveis entre o modelo hospedeiro "
    "e os modelos vinculados. Mostra coincidências, divergências e níveis ausentes."
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
    Level,
    BuiltInParameter,
    XYZ,
    Transform,
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


# ============================================================
# COLETA DE DADOS
# ============================================================

def _get_levels(document):
    """Retorna a lista ordenada dos níveis de um documento."""
    levels = []
    try:
        for lv in FilteredElementCollector(document).OfClass(Level):
            try:
                name = lv.Name
                elev = lv.Elevation
                levels.append({"name": name, "elevation": elev})
            except Exception:
                pass
    except Exception:
        pass
    levels.sort(key=lambda x: x["elevation"])
    return levels


def _get_loaded_links():
    """Retorna a lista das instâncias de link carregadas, com os seus documentos."""
    links = []
    for lnk in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        link_doc = lnk.GetLinkDocument()
        link_name = lnk.Name or "Desconhecido"
        if link_doc is None:
            continue
        links.append({
            "name": link_name,
            "doc": link_doc,
            "instance": lnk,
        })
    return links


TOLERANCE_MM = 1.0  # tolerância de 1 mm na comparação dos níveis
TOLERANCE_FT = TOLERANCE_MM / FEET_TO_MM


def compare_levels(host_levels, link_levels):
    """Compara os níveis do hospedeiro com os níveis do link.

    Retorna a lista de linhas da comparação.
    """
    rows = []
    link_by_name = {}
    for lv in link_levels:
        link_by_name[lv["name"]] = lv

    matched_link_names = set()

    for hlv in host_levels:
        name = hlv["name"]
        h_elev = hlv["elevation"]

        if name in link_by_name:
            llv = link_by_name[name]
            l_elev = llv["elevation"]
            diff = h_elev - l_elev
            matched_link_names.add(name)

            if abs(diff) < TOLERANCE_FT:
                status = "IGUAL"
            else:
                status = "COTA DIFERENTE"

            rows.append({
                "host_name": name,
                "host_elev": h_elev,
                "link_name": name,
                "link_elev": l_elev,
                "diff": diff,
                "status": status,
            })
        else:
            # Tenta achar um nível do link na mesma cota
            found = False
            for llv in link_levels:
                if llv["name"] in matched_link_names:
                    continue
                diff = h_elev - llv["elevation"]
                if abs(diff) < TOLERANCE_FT:
                    matched_link_names.add(llv["name"])
                    rows.append({
                        "host_name": name,
                        "host_elev": h_elev,
                        "link_name": llv["name"],
                        "link_elev": llv["elevation"],
                        "diff": diff,
                        "status": "RENOMEADO",
                    })
                    found = True
                    break
            if not found:
                rows.append({
                    "host_name": name,
                    "host_elev": h_elev,
                    "link_name": "-",
                    "link_elev": None,
                    "diff": None,
                    "status": "AUSENTE NO LINK",
                })

    # Níveis do link sem correspondência
    for llv in link_levels:
        if llv["name"] not in matched_link_names:
            rows.append({
                "host_name": "-",
                "host_elev": None,
                "link_name": llv["name"],
                "link_elev": llv["elevation"],
                "diff": None,
                "status": "AUSENTE NO HOSPEDEIRO",
            })

    # Ordena pela cota (a do hospedeiro primeiro, depois a do link)
    def sort_key(r):
        e = r["host_elev"] if r["host_elev"] is not None else r["link_elev"]
        return e if e is not None else 0.0
    rows.sort(key=sort_key)

    return rows


# ============================================================
# INTERFACE XAML
# ============================================================

XAML_STR = u"""\
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Compare Levels"
    Width="1000" SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="CanResizeWithGrip"
    MaxHeight="850">
  <ScrollViewer VerticalScrollBarVisibility="Auto">
  <Grid Margin="15">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Níveis do hospedeiro -->
    <GroupBox Grid.Row="0" Header="Níveis do modelo hospedeiro"
              Margin="0,0,0,10" FontWeight="Bold">
      <StackPanel Margin="8">
        <TextBlock x:Name="txt_host_name" FontWeight="Normal"
                   Margin="0,0,0,6"/>
        <DataGrid x:Name="dg_host_levels"
                  AutoGenerateColumns="False" IsReadOnly="True"
                  CanUserSortColumns="True"
                  HeadersVisibility="Column"
                  AlternatingRowBackground="#F0F4F8"
                  GridLinesVisibility="Horizontal"
                  BorderThickness="1" BorderBrush="#CCC"
                  MaxHeight="200"
                  FontWeight="Normal">
          <DataGrid.Columns>
            <DataGridTextColumn Header="Nome do nível"
                Binding="{Binding name}" Width="*" MinWidth="160"/>
            <DataGridTextColumn Header="Cota (m)"
                Binding="{Binding elev_m}" Width="100"/>
            <DataGridTextColumn Header="Cota (mm)"
                Binding="{Binding elev_mm}" Width="100"/>
          </DataGrid.Columns>
        </DataGrid>
      </StackPanel>
    </GroupBox>

    <!-- Comparação -->
    <GroupBox Grid.Row="1" Header="Comparação de níveis"
              Margin="0,0,0,10" FontWeight="Bold">
      <StackPanel Margin="8">
        <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
          <TextBlock Text="Comparar com: " FontWeight="Normal"
                     VerticalAlignment="Center"/>
          <ComboBox x:Name="cb_links" Width="420" Height="28"
                    FontWeight="Normal"/>
          <Button x:Name="btn_compare" Content="Comparar"
                  Width="80" Height="28" Margin="10,0,0,0"
                  FontSize="12" FontWeight="Bold"
                  Background="#2980B9" Foreground="White"/>
        </StackPanel>
        <DataGrid x:Name="dg_comparison"
                  AutoGenerateColumns="False" IsReadOnly="True"
                  CanUserSortColumns="True"
                  CanUserResizeColumns="True"
                  HeadersVisibility="Column"
                  AlternatingRowBackground="#F0F4F8"
                  GridLinesVisibility="Horizontal"
                  BorderThickness="1" BorderBrush="#CCC"
                  MaxHeight="320"
                  FontWeight="Normal"
                  Visibility="Collapsed">
          <DataGrid.Columns>
            <DataGridTextColumn Header="Nível do hospedeiro"
                Binding="{Binding host_name}" Width="*" MinWidth="140"/>
            <DataGridTextColumn Header="Cota hosp. (m)"
                Binding="{Binding host_elev}" Width="95"/>
            <DataGridTextColumn Header="Nível do link"
                Binding="{Binding link_name}" Width="*" MinWidth="140"/>
            <DataGridTextColumn Header="Cota link (m)"
                Binding="{Binding link_elev}" Width="95"/>
            <DataGridTextColumn Header="Dif. (mm)"
                Binding="{Binding diff_mm}" Width="80"/>
            <DataGridTextColumn Header="Status"
                Binding="{Binding status}" Width="170"/>
          </DataGrid.Columns>
        </DataGrid>
        <TextBlock x:Name="txt_no_comparison"
                   Text="Selecione um link e clique em Comparar"
                   Foreground="#999" FontStyle="Italic" FontWeight="Normal"
                   Margin="0,6,0,0"/>
      </StackPanel>
    </GroupBox>

    <!-- Resumo -->
    <TextBlock Grid.Row="2" x:Name="txt_summary"
               Foreground="#555" FontSize="11"
               Margin="0,0,0,10"/>

    <!-- Botões -->
    <StackPanel Grid.Row="3" Orientation="Horizontal"
                HorizontalAlignment="Right">
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

class HostLevelRow(object):
    def __init__(self, lv):
        self.name = lv["name"]
        self.elev_m = _fmt_m(lv["elevation"])
        self.elev_mm = _fmt_mm(lv["elevation"])


class CompareRow(object):
    def __init__(self, row):
        self._data = row
        self.host_name = row["host_name"]
        self.host_elev = _fmt_m(row["host_elev"]) if row["host_elev"] is not None else "-"
        self.link_name = row["link_name"]
        self.link_elev = _fmt_m(row["link_elev"]) if row["link_elev"] is not None else "-"
        if row["diff"] is not None:
            self.diff_mm = _fmt_mm(row["diff"])
        else:
            self.diff_mm = "-"
        self.status = row["status"]


# ============================================================
# CLASSE DA INTERFACE
# ============================================================

class CompareLevelsUI(object):
    def __init__(self):
        xaml_bytes = Encoding.UTF8.GetBytes(XAML_STR)
        stream = MemoryStream(xaml_bytes)
        self.window = XamlReader.Load(stream)
        stream.Close()

        self.txt_host_name = self.window.FindName("txt_host_name")
        self.dg_host_levels = self.window.FindName("dg_host_levels")
        self.cb_links = self.window.FindName("cb_links")
        self.btn_compare = self.window.FindName("btn_compare")
        self.dg_comparison = self.window.FindName("dg_comparison")
        self.txt_no_comparison = self.window.FindName("txt_no_comparison")
        self.txt_summary = self.window.FindName("txt_summary")
        self.btn_export = self.window.FindName("btn_export")
        self.btn_close = self.window.FindName("btn_close")

        self.btn_compare.Click += self.on_compare
        self.btn_export.Click += self.on_export
        self.btn_close.Click += self.on_close

        self.host_levels = []
        self.loaded_links = []
        self.comparison_rows = []

        self._populate()

    def _populate(self):
        host_title = doc.Title or "Modelo hospedeiro"
        self.txt_host_name.Text = u"Modelo: {}".format(host_title)

        # Níveis do hospedeiro
        self.host_levels = _get_levels(doc)
        host_rows = [HostLevelRow(lv) for lv in self.host_levels]
        self.dg_host_levels.ItemsSource = host_rows

        # Combo dos links
        self.loaded_links = _get_loaded_links()
        self.cb_links.Items.Clear()
        for lk in self.loaded_links:
            self.cb_links.Items.Add(lk["name"])
        if self.loaded_links:
            self.cb_links.SelectedIndex = 0

        self.txt_summary.Text = u"{} níveis no hospedeiro  |  {} links carregados".format(
            len(self.host_levels), len(self.loaded_links),
        )

    def on_compare(self, sender, args):
        idx = self.cb_links.SelectedIndex
        if idx < 0 or idx >= len(self.loaded_links):
            forms.alert("Selecione primeiro um modelo vinculado.", title="Comparar")
            return

        link_info = self.loaded_links[idx]
        link_levels = _get_levels(link_info["doc"])

        rows = compare_levels(self.host_levels, link_levels)
        self.comparison_rows = rows

        compare_display = [CompareRow(r) for r in rows]

        if compare_display:
            self.dg_comparison.ItemsSource = compare_display
            self.dg_comparison.Visibility = Visibility.Visible
            self.txt_no_comparison.Visibility = Visibility.Collapsed
        else:
            self.dg_comparison.Visibility = Visibility.Collapsed
            self.txt_no_comparison.Text = u"Nenhum nível para comparar"
            self.txt_no_comparison.Visibility = Visibility.Visible

        # Resumo
        total = len(rows)
        matched = sum(1 for r in rows if r["status"] == "IGUAL")
        differ = sum(1 for r in rows if r["status"] == "COTA DIFERENTE")
        renamed = sum(1 for r in rows if r["status"] == "RENOMEADO")
        missing_link = sum(1 for r in rows if r["status"] == "AUSENTE NO LINK")
        missing_host = sum(1 for r in rows if r["status"] == "AUSENTE NO HOSPEDEIRO")

        parts = [u"{} níveis comparados".format(total)]
        if matched:
            parts.append(u"{} iguais".format(matched))
        if differ:
            parts.append(u"{} com cota diferente".format(differ))
        if renamed:
            parts.append(u"{} renomeados".format(renamed))
        if missing_link:
            parts.append(u"{} ausentes no link".format(missing_link))
        if missing_host:
            parts.append(u"{} ausentes no hospedeiro".format(missing_host))

        self.txt_summary.Text = u"  |  ".join(parts)

    def on_export(self, sender, args):
        if not self.comparison_rows:
            forms.alert(
                u"Faça uma comparação primeiro.",
                title="Exportar",
            )
            return

        filepath = forms.save_file(file_ext="csv")
        if not filepath:
            return

        lines = []
        lines.append(
            u"Nível do hospedeiro,Cota do hospedeiro (m),Nível do link,"
            u"Cota do link (m),Dif. (mm),Status"
        )

        for r in self.comparison_rows:
            h_elev = _fmt_m(r["host_elev"]) if r["host_elev"] is not None else ""
            l_elev = _fmt_m(r["link_elev"]) if r["link_elev"] is not None else ""
            diff = _fmt_mm(r["diff"]) if r["diff"] is not None else ""
            lines.append(u"{},{},{},{},{},{}".format(
                r["host_name"], h_elev,
                r["link_name"], l_elev,
                diff, r["status"],
            ))

        with open(filepath, "w") as f:
            f.write("\n".join(lines))

        forms.alert(
            u"{} linhas exportadas para:\n{}".format(len(lines), filepath),
            title=u"Exportação concluída",
        )

    def on_close(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()


# ============================================================
# PONTO DE ENTRADA
# ============================================================

ui = CompareLevelsUI()
ui.show()
