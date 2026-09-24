#! python3
# -*- coding: utf-8 -*-
"""Clash Resolver.

Detecta clashes geométricos (sobreposição de AABB) entre o modelo HOST (o
lado cujos elementos são movidos) e um link Revit (o lado do obstáculo) e,
para cada clash, calcula o Vetor Mínimo de Translação (MTV) necessário para
empurrar o elemento do host para fora do obstáculo no eixo de menor penetração.

Os clashes cuja penetração fica dentro de um limite definido pelo usuário (mm)
são marcados como resolvíveis automaticamente. O usuário seleciona as linhas e
clica em "Resolver selecionados": numa única Transaction os elementos do host
são movidos pelo seu MTV (penetração + folga), e as bounding boxes deixam de
se sobrepor.

Por que só os elementos do host se movem:
    Os elementos que vivem dentro de um .rvt vinculado pertencem a outro
    Document e não podem ser movidos a partir do host. O host só pode mover a
    RevitLinkInstance inteira. Por isso o lado móvel é sempre o modelo HOST;
    o link é tratado como um obstáculo fixo.

Autor: Paulo Giavoni
Motor: CPython3
"""
from __future__ import print_function

__title__ = "Clash\nResolver"
__author__ = "Paulo Giavoni"

import os
import traceback

import clr  # noqa: F401  (needed for .NET imports below)

from System import Array
from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows import (
    MessageBox, MessageBoxButton, MessageBoxImage, MessageBoxResult,
)
from System.Windows.Markup import XamlReader

from Autodesk.Revit.DB import (
    BuiltInCategory,
    ElementId,
    ElementTransformUtils,
    FilteredElementCollector,
    RevitLinkInstance,
    Transaction,
    TransactionStatus,
    Transform,
    XYZ,
)

# NOTA: como o ClashDetective, este script evita de propósito importar os
# módulos Python do `pyrevit`, porque a cadeia de imports deles quebra no
# CPython3 nesta build. Usamos `__revit__` direto + um wrapper de MessageBox.
uiapp = __revit__  # noqa: F821 – injetado pelo pyRevit
uidoc = uiapp.ActiveUIDocument
doc = uidoc.Document

_FT_TO_M = 0.3048
_FT_TO_MM = 304.8
_MM_TO_FT = 1.0 / 304.8


def _alert(message, title="Clash Resolver", yes_no=False):
    """Substituto leve de pyrevit.forms.alert (seguro no CPython3)."""
    if yes_no:
        res = MessageBox.Show(
            message, title, MessageBoxButton.YesNo,
            MessageBoxImage.Question)
        return res == MessageBoxResult.Yes
    MessageBox.Show(message, title, MessageBoxButton.OK,
                    MessageBoxImage.Information)
    return True


def _id_int(eid):
    """Valor numérico de um ElementId em qualquer versão do Revit.

    ``ElementId.IntegerValue`` foi removido no Revit 2026 e ``Value``
    só existe a partir do Revit 2024, então é preciso tentar as duas formas.
    """
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


# ---------------------------------------------------------------------------
# Categorias (mesmos presets do ClashDetective)
# ---------------------------------------------------------------------------
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
    BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_Floors,
    BuiltInCategory.OST_Ceilings,
    BuiltInCategory.OST_Roofs,
    BuiltInCategory.OST_Doors,
    BuiltInCategory.OST_Windows,
    BuiltInCategory.OST_Stairs,
    BuiltInCategory.OST_Furniture,
    BuiltInCategory.OST_FurnitureSystems,
    BuiltInCategory.OST_Casework,
    BuiltInCategory.OST_SpecialityEquipment,
    BuiltInCategory.OST_GenericModel,
]

_STR_CATEGORIES = [
    BuiltInCategory.OST_StructuralColumns,
    BuiltInCategory.OST_StructuralFraming,
    BuiltInCategory.OST_StructuralFoundation,
    BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_Floors,
]

_BIC_LABELS = {}


def _bic_label(bic):
    """Rótulo legível da BuiltInCategory, com cache."""
    key = int(bic)
    if key in _BIC_LABELS:
        return _BIC_LABELS[key]
    try:
        cat = doc.Settings.Categories.get_Item(bic)
        label = cat.Name if cat is not None else str(bic)
    except Exception:
        label = str(bic).replace("OST_", "")
    _BIC_LABELS[key] = label
    return label


# ---------------------------------------------------------------------------
# Fontes
# ---------------------------------------------------------------------------
class Source(object):
    __slots__ = ("label", "doc", "transform", "is_host", "link_instance",
                 "link_id")

    def __init__(self, label, source_doc, transform, is_host,
                 link_instance=None, link_id=None):
        self.label = label
        self.doc = source_doc
        self.transform = transform
        self.is_host = is_host
        self.link_instance = link_instance
        self.link_id = link_id


def _host_source():
    return Source("[Host] " + (doc.Title or "Modelo atual"),
                  doc, Transform.Identity, True)


def _list_link_sources():
    """Devolve list[Source] dos links carregados válidos (lado obstáculo)."""
    sources = []
    for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        ldoc = li.GetLinkDocument()
        if ldoc is None:
            continue
        try:
            tx = li.GetTotalTransform()
        except Exception:
            tx = Transform.Identity
        name = li.Name or (ldoc.Title or "Link")
        sources.append(Source("[Link] " + name, ldoc, tx, False, li, li.Id))
    return sources


# ---------------------------------------------------------------------------
# Coleta das bounding boxes
# ---------------------------------------------------------------------------
class BBoxItem(object):
    __slots__ = ("eid", "cat_label", "level_name",
                 "min_x", "min_y", "min_z", "max_x", "max_y", "max_z")

    def __init__(self, eid, cat_label, level_name, mn, mx):
        self.eid = eid
        self.cat_label = cat_label
        self.level_name = level_name
        self.min_x, self.min_y, self.min_z = mn
        self.max_x, self.max_y, self.max_z = mx


def _world_aabb(bbox, transform):
    """Transforma os 8 cantos de uma BoundingBoxXYZ numa AABB global."""
    mn, mx = bbox.Min, bbox.Max
    corners = [
        XYZ(mn.X, mn.Y, mn.Z), XYZ(mx.X, mn.Y, mn.Z),
        XYZ(mn.X, mx.Y, mn.Z), XYZ(mx.X, mx.Y, mn.Z),
        XYZ(mn.X, mn.Y, mx.Z), XYZ(mx.X, mn.Y, mx.Z),
        XYZ(mn.X, mx.Y, mx.Z), XYZ(mx.X, mx.Y, mx.Z),
    ]
    pts = [transform.OfPoint(c) for c in corners]
    xs = [p.X for p in pts]
    ys = [p.Y for p in pts]
    zs = [p.Z for p in pts]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _level_name(elem, source_doc):
    try:
        lid = elem.LevelId
        if lid is not None and lid != ElementId.InvalidElementId:
            lev = source_doc.GetElement(lid)
            if lev is not None:
                return lev.Name
    except Exception:
        pass
    return ""


def _collect_bbox_items(source, bic_list, ignore_pinned):
    """Devolve list[BBoxItem] de uma fonte, filtrada por categorias."""
    items = []
    sdoc = source.doc
    tx = source.transform
    for bic in bic_list:
        try:
            collector = (FilteredElementCollector(sdoc)
                         .OfCategory(bic)
                         .WhereElementIsNotElementType())
        except Exception:
            continue
        cat_label = _bic_label(bic)
        for elem in collector:
            try:
                if ignore_pinned and getattr(elem, "Pinned", False):
                    continue
                bbox = elem.get_BoundingBox(None)
                if bbox is None:
                    continue
                mn, mx = _world_aabb(bbox, tx)
                items.append(BBoxItem(elem.Id, cat_label,
                                      _level_name(elem, sdoc), mn, mx))
            except Exception:
                continue
    return items


# ---------------------------------------------------------------------------
# Hash espacial
# ---------------------------------------------------------------------------
def _build_grid(items, cell_ft=10.0):
    grid = {}
    inv = 1.0 / cell_ft
    import math
    for idx, it in enumerate(items):
        ix0 = int(math.floor(it.min_x * inv))
        iy0 = int(math.floor(it.min_y * inv))
        iz0 = int(math.floor(it.min_z * inv))
        ix1 = int(math.floor(it.max_x * inv))
        iy1 = int(math.floor(it.max_y * inv))
        iz1 = int(math.floor(it.max_z * inv))
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                for iz in range(iz0, iz1 + 1):
                    grid.setdefault((ix, iy, iz), []).append(idx)
    return grid, inv


# ---------------------------------------------------------------------------
# Resultado do clash + MTV
# ---------------------------------------------------------------------------
class ResolveClash(object):
    __slots__ = ("cid", "host_eid", "host_cat", "obs_id", "obs_cat",
                 "level_name", "cx", "cy", "cz", "pen_ft", "axis",
                 "translation", "resolvable")

    def __init__(self, cid, host_eid, host_cat, obs_id, obs_cat,
                 level_name, center, pen_ft, axis, translation, resolvable):
        self.cid = cid
        self.host_eid = host_eid
        self.host_cat = host_cat
        self.obs_id = obs_id
        self.obs_cat = obs_cat
        self.level_name = level_name
        self.cx, self.cy, self.cz = center
        self.pen_ft = pen_ft
        self.axis = axis
        self.translation = translation
        self.resolvable = resolvable


def _mtv(a, b, ox, oy, oz, gap_ft):
    """Escolhe o eixo de menor penetração; devolve (pen_ft, eixo, XYZ)."""
    ca_x = (a.min_x + a.max_x) * 0.5
    ca_y = (a.min_y + a.max_y) * 0.5
    ca_z = (a.min_z + a.max_z) * 0.5
    cb_x = (b.min_x + b.max_x) * 0.5
    cb_y = (b.min_y + b.max_y) * 0.5
    cb_z = (b.min_z + b.max_z) * 0.5
    if ox <= oy and ox <= oz:
        sign = 1.0 if ca_x >= cb_x else -1.0
        return ox, "X", XYZ(sign * (ox + gap_ft), 0.0, 0.0)
    if oy <= ox and oy <= oz:
        sign = 1.0 if ca_y >= cb_y else -1.0
        return oy, "Y", XYZ(0.0, sign * (oy + gap_ft), 0.0)
    sign = 1.0 if ca_z >= cb_z else -1.0
    return oz, "Z", XYZ(0.0, 0.0, sign * (oz + gap_ft))


def detect_resolvable(host_items, obs_items, gap_ft, limit_ft, same_source):
    """Detecta sobreposições reais de AABB (host x obstáculo); calcula o MTV."""
    import math
    grid, inv = _build_grid(obs_items, cell_ft=10.0)
    clashes = []
    cid = 0
    for a in host_items:
        ix0 = int(math.floor(a.min_x * inv))
        iy0 = int(math.floor(a.min_y * inv))
        iz0 = int(math.floor(a.min_z * inv))
        ix1 = int(math.floor(a.max_x * inv))
        iy1 = int(math.floor(a.max_y * inv))
        iz1 = int(math.floor(a.max_z * inv))
        seen = set()
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                for iz in range(iz0, iz1 + 1):
                    bucket = grid.get((ix, iy, iz))
                    if not bucket:
                        continue
                    for j in bucket:
                        if j in seen:
                            continue
                        seen.add(j)
                        b = obs_items[j]
                        if same_source and a.eid == b.eid:
                            continue
                        ox = min(a.max_x, b.max_x) - max(a.min_x, b.min_x)
                        if ox <= 0.0:
                            continue
                        oy = min(a.max_y, b.max_y) - max(a.min_y, b.min_y)
                        if oy <= 0.0:
                            continue
                        oz = min(a.max_z, b.max_z) - max(a.min_z, b.min_z)
                        if oz <= 0.0:
                            continue
                        pen, axis, tvec = _mtv(a, b, ox, oy, oz, gap_ft)
                        cx = (max(a.min_x, b.min_x) +
                              min(a.max_x, b.max_x)) * 0.5
                        cy = (max(a.min_y, b.min_y) +
                              min(a.max_y, b.max_y)) * 0.5
                        cz = (max(a.min_z, b.min_z) +
                              min(a.max_z, b.max_z)) * 0.5
                        cid += 1
                        clashes.append(ResolveClash(
                            cid, a.eid, a.cat_label, _id_int(b.eid),
                            b.cat_label, a.level_name or b.level_name,
                            (cx, cy, cz), pen, axis, tvec,
                            pen <= limit_ft))
    return clashes


# ---------------------------------------------------------------------------
# Resolução (a única parte que escreve no modelo)
# ---------------------------------------------------------------------------
def resolve_rows(rows):
    """Move os elementos do host pelo seu MTV dentro de uma única Transaction.

    Devolve (moved_count, list[(cid, motivo)] dos pulados).
    """
    moved = 0
    skipped = []
    moved_ids = set()
    t = Transaction(doc, "Clash Resolver - mover elementos")
    t.Start()
    try:
        for r in rows:
            c = r._clash
            key = _id_int(c.host_eid)
            if key in moved_ids:
                r.status = "Pulado: elemento já movido neste lote"
                skipped.append((c.cid, "elemento já movido no lote"))
                continue
            el = doc.GetElement(c.host_eid)
            if el is None:
                r.status = "Pulado: elemento não existe"
                skipped.append((c.cid, "elemento não existe"))
                continue
            if getattr(el, "Pinned", False):
                r.status = "Pulado: elemento pinado"
                skipped.append((c.cid, "elemento pinado"))
                continue
            try:
                ElementTransformUtils.MoveElement(doc, c.host_eid,
                                                  c.translation)
                moved_ids.add(key)
                r.status = "Resolvido"
                moved += 1
            except Exception as ex:
                r.status = "Falhou: " + str(ex)[:50]
                skipped.append((c.cid, str(ex)[:80]))
        t.Commit()
    except Exception:
        if t.GetStatus() == TransactionStatus.Started:
            t.RollBack()
        raise
    return moved, skipped


# ---------------------------------------------------------------------------
# Interface WPF
# ---------------------------------------------------------------------------
_XAML = u"""<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Clash Resolver" Width="900" Height="700"
        WindowStartupLocation="CenterScreen"
        ResizeMode="CanResize" FontFamily="Segoe UI" FontSize="12">
  <Grid Margin="12">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Fontes -->
    <GroupBox Grid.Row="0" Header="Fontes" Padding="8" Margin="0,0,0,8">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="170"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="170"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <TextBlock Grid.Column="0" VerticalAlignment="Center"
                   Text="Mover (Host):"/>
        <TextBlock Grid.Column="1" x:Name="tbHost" VerticalAlignment="Center"
                   FontWeight="Bold" Margin="4,0,12,0"/>
        <TextBlock Grid.Column="2" VerticalAlignment="Center"
                   Text="Obstáculo (Link):"/>
        <ComboBox  Grid.Column="3" x:Name="cbObs" Margin="4,0,0,0"/>
      </Grid>
    </GroupBox>

    <!-- Categorias -->
    <GroupBox Grid.Row="1" Header="Categorias" Padding="8" Margin="0,0,0,8">
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <StackPanel Grid.Column="0">
          <TextBlock Text="Disciplinas do Host (movido)" FontWeight="Bold"
                     Margin="0,0,0,4"/>
          <CheckBox x:Name="cbHArch" Content="Arquitetura"/>
          <CheckBox x:Name="cbHStr"  Content="Estrutura"/>
          <CheckBox x:Name="cbHMep"  Content="MEP" IsChecked="True"/>
        </StackPanel>
        <StackPanel Grid.Column="1">
          <TextBlock Text="Disciplinas do obstáculo" FontWeight="Bold"
                     Margin="0,0,0,4"/>
          <CheckBox x:Name="cbOArch" Content="Arquitetura" IsChecked="True"/>
          <CheckBox x:Name="cbOStr"  Content="Estrutura" IsChecked="True"/>
          <CheckBox x:Name="cbOMep"  Content="MEP"/>
        </StackPanel>
      </Grid>
    </GroupBox>

    <!-- Opções -->
    <GroupBox Grid.Row="2" Header="Regra" Padding="8" Margin="0,0,0,8">
      <StackPanel Orientation="Horizontal">
        <TextBlock Text="Limite p/ resolver (mm):" VerticalAlignment="Center"/>
        <TextBox   x:Name="tbLimit" Text="50" Width="60" Margin="6,0,16,0"/>
        <TextBlock Text="Folga após mover (mm):" VerticalAlignment="Center"/>
        <TextBox   x:Name="tbGap" Text="2" Width="60" Margin="6,0,16,0"/>
        <CheckBox  x:Name="cbIgnorePinned" Content="Ignorar pinados"
                   IsChecked="True" VerticalAlignment="Center"/>
      </StackPanel>
    </GroupBox>

    <!-- Linha de execução -->
    <StackPanel Grid.Row="3" Orientation="Horizontal" Margin="0,0,0,8">
      <Button x:Name="btnRun" Content="Detectar clashes" Padding="14,5"
              Background="#2C3E50" Foreground="White" FontWeight="Bold"/>
      <Button x:Name="btnSelAuto" Content="Selecionar resolvíveis"
              Padding="12,5" Margin="8,0,0,0"/>
      <TextBlock x:Name="tbStatus" VerticalAlignment="Center"
                 Margin="14,0,0,0" Foreground="#555"/>
    </StackPanel>

    <!-- Resultados -->
    <DataGrid Grid.Row="4" x:Name="dgResults" AutoGenerateColumns="False"
              IsReadOnly="True" SelectionMode="Extended"
              SelectionUnit="FullRow"
              GridLinesVisibility="Horizontal" HeadersVisibility="Column"
              AlternatingRowBackground="#F5F7FA">
      <DataGrid.Columns>
        <DataGridTextColumn Header="#"          Binding="{Binding cid}"      Width="40"/>
        <DataGridTextColumn Header="Auto"       Binding="{Binding auto}"     Width="44"/>
        <DataGridTextColumn Header="Host id"    Binding="{Binding host_id}"  Width="70"/>
        <DataGridTextColumn Header="Host cat"   Binding="{Binding host_cat}" Width="*"/>
        <DataGridTextColumn Header="Obst id"    Binding="{Binding obs_id}"   Width="70"/>
        <DataGridTextColumn Header="Obst cat"   Binding="{Binding obs_cat}"  Width="*"/>
        <DataGridTextColumn Header="Nível"      Binding="{Binding level}"    Width="90"/>
        <DataGridTextColumn Header="Penetr (mm)" Binding="{Binding pen}"     Width="80"/>
        <DataGridTextColumn Header="Eixo"       Binding="{Binding axis}"     Width="44"/>
        <DataGridTextColumn Header="Mover (mm)" Binding="{Binding move}"     Width="80"/>
        <DataGridTextColumn Header="Status"     Binding="{Binding status}"   Width="150"/>
      </DataGrid.Columns>
    </DataGrid>

    <!-- Rodapé -->
    <StackPanel Grid.Row="5" Orientation="Horizontal"
                HorizontalAlignment="Right" Margin="0,8,0,0">
      <Button x:Name="btnResolve" Content="Resolver selecionados"
              Padding="14,5" Margin="0,0,8,0"
              Background="#27AE60" Foreground="White" FontWeight="Bold"/>
      <Button x:Name="btnZoom"  Content="Zoom no host" Padding="12,5" Margin="0,0,8,0"/>
      <Button x:Name="btnClose" Content="Fechar"       Padding="12,5"/>
    </StackPanel>
  </Grid>
</Window>"""


class ClashRow(object):
    """Linha leve para o binding do DataGrid (espelha o ClashDetective)."""
    def __init__(self, c, gap_ft):
        self.cid = c.cid
        self.auto = u"✓" if c.resolvable else u"—"
        self.host_id = _id_int(c.host_eid)
        self.host_cat = c.host_cat
        self.obs_id = c.obs_id
        self.obs_cat = c.obs_cat
        self.level = c.level_name or "-"
        self.pen = "{0:.1f}".format(c.pen_ft * _FT_TO_MM)
        self.axis = c.axis
        self.move = "{0:.1f}".format((c.pen_ft + gap_ft) * _FT_TO_MM)
        self.status = "Resolvível" if c.resolvable else "Acima do limite"
        self._clash = c


class ResolverWindow(object):
    def __init__(self, host_source, link_sources):
        self.host_source = host_source
        self.link_sources = link_sources
        ms = MemoryStream(Encoding.UTF8.GetBytes(_XAML))
        self.win = XamlReader.Load(ms)

        self.win.FindName("tbHost").Text = host_source.label

        self.cbObs = self.win.FindName("cbObs")
        for s in link_sources:
            self.cbObs.Items.Add(s.label)
        if link_sources:
            self.cbObs.SelectedIndex = 0

        self.cbHArch = self.win.FindName("cbHArch")
        self.cbHStr = self.win.FindName("cbHStr")
        self.cbHMep = self.win.FindName("cbHMep")
        self.cbOArch = self.win.FindName("cbOArch")
        self.cbOStr = self.win.FindName("cbOStr")
        self.cbOMep = self.win.FindName("cbOMep")

        self.tbLimit = self.win.FindName("tbLimit")
        self.tbGap = self.win.FindName("tbGap")
        self.cbIgnorePinned = self.win.FindName("cbIgnorePinned")

        self.tbStatus = self.win.FindName("tbStatus")
        self.dg = self.win.FindName("dgResults")

        self.win.FindName("btnRun").Click += self._on_run
        self.win.FindName("btnSelAuto").Click += self._on_select_auto
        self.win.FindName("btnResolve").Click += self._on_resolve
        self.win.FindName("btnZoom").Click += self._on_zoom
        self.win.FindName("btnClose").Click += self._on_close
        self.dg.MouseDoubleClick += self._on_row_dbl

        self._rows = []

    # ---- auxiliares ----
    def _disc_cats(self, arch, struc, mep):
        cats = []
        names = []
        if arch:
            cats.extend(_ARCH_CATEGORIES); names.append("Arquitetura")
        if struc:
            cats.extend(_STR_CATEGORIES);  names.append("Estrutura")
        if mep:
            cats.extend(_MEP_CATEGORIES);  names.append("MEP")
        seen = set(); uniq = []
        for c in cats:
            k = int(c)
            if k in seen:
                continue
            seen.add(k); uniq.append(c)
        return uniq, ", ".join(names) if names else "(nenhuma)"

    def _parse_mm(self, textbox, default):
        try:
            return float((textbox.Text or "").replace(",", "."))
        except ValueError:
            return default

    def _set_status(self, msg):
        self.tbStatus.Text = msg

    def _refresh_grid(self):
        self.dg.ItemsSource = None
        self.dg.ItemsSource = self._rows

    # ---- tratadores de eventos ----
    def _on_run(self, _s, _e):
        try:
            if not self.link_sources:
                _alert("Nenhum link carregado no modelo.\n\nO Clash Resolver "
                       "compara o Host com um link (o obstáculo). Carregue um "
                       "link e tente novamente.")
                return
            obs_source = self.link_sources[self.cbObs.SelectedIndex]

            host_cats, _ = self._disc_cats(
                self.cbHArch.IsChecked, self.cbHStr.IsChecked,
                self.cbHMep.IsChecked)
            obs_cats, _ = self._disc_cats(
                self.cbOArch.IsChecked, self.cbOStr.IsChecked,
                self.cbOMep.IsChecked)
            if not host_cats or not obs_cats:
                _alert("Selecione ao menos uma disciplina para cada lado.")
                return

            limit_mm = self._parse_mm(self.tbLimit, 50.0)
            gap_mm = self._parse_mm(self.tbGap, 2.0)
            limit_ft = limit_mm * _MM_TO_FT
            gap_ft = gap_mm * _MM_TO_FT
            self._gap_ft = gap_ft
            ignore_pinned = bool(self.cbIgnorePinned.IsChecked)

            self._set_status("Coletando bounding boxes…")
            self.win.UpdateLayout()
            host_items = _collect_bbox_items(
                self.host_source, host_cats, ignore_pinned)
            obs_items = _collect_bbox_items(
                obs_source, obs_cats, False)

            self._set_status("Detectando clashes ({0} × {1})…".format(
                len(host_items), len(obs_items)))
            self.win.UpdateLayout()
            clashes = detect_resolvable(
                host_items, obs_items, gap_ft, limit_ft, same_source=False)

            self._rows = [ClashRow(c, gap_ft) for c in clashes]
            self._refresh_grid()
            n_auto = sum(1 for c in clashes if c.resolvable)
            self._set_status(
                "{0} clashes | {1} resolvíveis (<= {2:.0f} mm) | "
                "{3} acima do limite.".format(
                    len(clashes), n_auto, limit_mm, len(clashes) - n_auto))
        except Exception as ex:
            traceback.print_exc()
            _alert("Falha na detecção:\n{0}".format(ex))

    def _on_select_auto(self, _s, _e):
        try:
            if not self._rows:
                return
            self.dg.SelectedItems.Clear()
            for r in self._rows:
                if r._clash.resolvable and r.status != "Resolvido":
                    self.dg.SelectedItems.Add(r)
            self._set_status("{0} clashes resolvíveis selecionados.".format(
                self.dg.SelectedItems.Count))
        except Exception as ex:
            traceback.print_exc()
            _alert("Falha ao selecionar:\n{0}".format(ex))

    def _on_resolve(self, _s, _e):
        rows = list(self.dg.SelectedItems)
        if not rows:
            _alert("Selecione ao menos um clash na lista.\n\nDica: use "
                   "'Selecionar resolvíveis' para marcar todos abaixo do "
                   "limite.")
            return
        n_over = sum(1 for r in rows if not r._clash.resolvable)
        msg = ("Mover {0} elemento(s) do Host para resolver os clashes "
               "selecionados?".format(len(rows)))
        if n_over:
            msg += ("\n\nATENÇÃO: {0} estão ACIMA do limite e exigem um "
                    "deslocamento grande. Confirma mesmo assim?".format(n_over))
        if not _alert(msg, yes_no=True):
            return
        try:
            moved, skipped = resolve_rows(rows)
            self._refresh_grid()
            txt = "{0} elemento(s) movido(s).".format(moved)
            if skipped:
                txt += " {0} pulado(s)/falha(s).".format(len(skipped))
            txt += " Rode novamente para revalidar."
            self._set_status(txt)
        except Exception as ex:
            traceback.print_exc()
            _alert("Falha ao resolver (transação revertida):\n{0}".format(ex))

    def _on_zoom(self, _s, _e):
        self._zoom_selected()

    def _on_row_dbl(self, _s, _e):
        self._zoom_selected()

    def _zoom_selected(self):
        row = self.dg.SelectedItem
        if row is None:
            return
        c = getattr(row, "_clash", None)
        if c is None:
            return
        try:
            ids = Array[ElementId]([c.host_eid])
            uidoc.Selection.SetElementIds(ids)
            uidoc.ShowElements(ids)
        except Exception:
            traceback.print_exc()

    def _on_close(self, _s, _e):
        self.win.Close()

    def show(self):
        self.win.ShowDialog()


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------
def main():
    host = _host_source()
    links = _list_link_sources()
    if not links:
        _alert("Nenhum link Revit carregado.\n\nO Clash Resolver move "
               "elementos do Host que colidem com um link (obstáculo). "
               "Carregue ao menos um link e tente novamente.")
        return
    ResolverWindow(host, links).show()


def _dump_error():
    """Grava o traceback Python completo na Área de Trabalho e o mostra.

    Rede de segurança para diagnóstico: o diálogo genérico 'Command Failure'
    do Revit esconde os frames Python reais, por isso os capturamos aqui.
    """
    msg = traceback.format_exc()
    try:
        desk = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        if not os.path.isdir(desk):
            desk = os.path.expanduser("~")
        with open(os.path.join(desk, "ClashResolver_error.txt"), "w") as f:
            f.write(msg)
    except Exception:
        pass
    try:
        _alert(msg[:1800], title="Clash Resolver - ERRO (detalhe)")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _dump_error()
        raise
