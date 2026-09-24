# -*- coding: utf-8 -*-
__title__ = "Smart\nLocation"
__doc__ = (
    "Selecione um link, importe os seus ambientes (Rooms) e localize cada "
    "elemento do modelo local dentro dos ambientes do link.\n\n"
    "O resultado é gravado em um parâmetro dos elementos."
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


# ─────────── AUXILIARES DE UNIDADE ───────────
try:
    from Autodesk.Revit.DB import UnitTypeId, UnitUtils, ForgeTypeId

    def _ft_to_m(feet):
        return UnitUtils.ConvertFromInternalUnits(feet, UnitTypeId.Meters)
except Exception:
    def _ft_to_m(feet):
        return feet * 0.3048


def _id_int(eid):
    """Valor numérico de um ElementId em qualquer versão do Revit.

    ``ElementId.IntegerValue`` foi removido no Revit 2026 e ``Value`` só
    existe a partir do Revit 2024, então é preciso tentar as duas grafias.
    """
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


# ─────────── COLETA DOS LINKS ───────────
_all_links = (
    FilteredElementCollector(doc)
    .OfClass(RevitLinkInstance)
    .ToElements()
)

if not _all_links:
    forms.alert("Nenhum link do Revit encontrado no projeto.", exitscript=True)

_link_dict = {}
for lnk in _all_links:
    link_doc = lnk.GetLinkDocument()
    if link_doc:
        name = link_doc.Title
        _link_dict[name] = lnk

if not _link_dict:
    forms.alert("Nenhum link carregado encontrado.", exitscript=True)


# ─────────── EXTRAÇÃO DOS AMBIENTES DO LINK ───────────
def get_rooms_from_link(link_instance):
    """Extrai os ambientes do documento vinculado, com a geometria transformada."""
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
        # Ignora ambientes não posicionados ou não delimitados
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

        # Nome do nível
        level_name = ""
        if room_level:
            try:
                lvl_id = room_level.AsElementId()
                lvl_elem = link_doc.GetElement(lvl_id)
                if lvl_elem:
                    level_name = lvl_elem.Name
            except Exception:
                pass

        # Ponto do ambiente (Location), levado às coordenadas do hospedeiro
        loc_pt = room.Location.Point
        transformed_pt = transform.OfPoint(loc_pt)

        # Bounding box, também transformada
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
    """Verifica se um ponto cai dentro da bounding box transformada do
    ambiente, com uma tolerância vertical (pés)."""
    bb_min = room_data["bb_min"]
    bb_max = room_data["bb_max"]

    return (
        bb_min.X <= point.X <= bb_max.X
        and bb_min.Y <= point.Y <= bb_max.Y
        and (bb_min.Z - tolerance) <= point.Z <= (bb_max.Z + tolerance)
    )


def point_in_room_precise(point, room_data):
    """Usa a API Room.IsPointInRoom do Revit, levando o ponto do hospedeiro
    de volta ao espaço de coordenadas do link pela transformação inversa."""
    room = room_data["room"]
    inv_transform = room_data["transform"].Inverse

    # Leva o ponto do hospedeiro de volta ao espaço do link
    link_point = inv_transform.OfPoint(point)

    try:
        return room.IsPointInRoom(link_point)
    except Exception:
        return False


def get_element_location_point(element):
    """Extrai um ponto representativo de um elemento."""
    loc = element.Location
    if loc is None:
        # alternativa: centro da bounding box
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

    # LocationCurve – usa o ponto médio
    try:
        crv = loc.Curve
        return crv.Evaluate(0.5, True)
    except Exception:
        pass

    # Alternativa: bounding box
    bb = element.get_BoundingBox(None)
    if bb:
        return XYZ(
            (bb.Min.X + bb.Max.X) / 2.0,
            (bb.Min.Y + bb.Max.Y) / 2.0,
            (bb.Min.Z + bb.Max.Z) / 2.0,
        )
    return None


# ─────────── BUSCA ESPACIAL ───────────
def find_room_for_element(element, rooms_data):
    """Encontra qual ambiente do link contém um elemento.
    Usa uma abordagem em duas passadas:
      1. Filtro rápido por bounding box
      2. IsPointInRoom preciso nos candidatos que sobraram
    Retorna um dict com os dados do ambiente, ou None.
    """
    pt = get_element_location_point(element)
    if pt is None:
        return None

    # Passada 1 – pré-filtro por bounding box (rápido)
    candidates = [r for r in rooms_data if point_in_room_bb(pt, r)]

    if not candidates:
        # tenta de novo com tolerância maior, para MEP acima do forro
        candidates = [r for r in rooms_data if point_in_room_bb(pt, r, tolerance=3.0)]

    # Passada 2 – verificação precisa
    for room_data in candidates:
        if point_in_room_precise(pt, room_data):
            return room_data

    # Se a verificação precisa falhou mas havia candidatos por BB, retorna o melhor
    if candidates:
        # ordena pela distância ao centro do ambiente
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


# ─────────── LISTAS DE CATEGORIAS ───────────
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
    """Rótulo legível da categoria a partir do enum BuiltInCategory."""
    try:
        cat = doc.Settings.Categories.get_Item(bic)
        if cat:
            return cat.Name
    except Exception:
        pass
    return str(bic).replace("OST_", "")


# ─────────── CRIAÇÃO E GRAVAÇÃO DO PARÂMETRO ───────────
PARAM_NAME = "SL_Room"
_param_ensured = False


def _ensure_param_exists(categories_to_bind):
    """Cria o parâmetro compartilhado de ambiente nas categorias dadas, se faltar.
    Usa um arquivo de parâmetros compartilhados temporário, para não poluir o do usuário."""
    global _param_ensured
    if _param_ensured:
        return

    # Verifica se o parâmetro já existe em pelo menos uma categoria
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

    # Monta um CategorySet para o binding
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

    # Guarda o caminho do arquivo de parâmetros compartilhados atual e cria um temporário
    app = doc.Application
    original_spf = app.SharedParametersFilename
    tmp_path = os.path.join(tempfile.gettempdir(), "_SmartLocation_sp.txt")

    try:
        # Cria o arquivo temporário de parâmetros compartilhados
        with open(tmp_path, "w") as f:
            f.write("")
        app.SharedParametersFilename = tmp_path
        sp_file = app.OpenSharedParameterFile()

        # Cria ou obtém o grupo
        group = sp_file.Groups.get_Item("SmartLocation")
        if group is None:
            group = sp_file.Groups.Create("SmartLocation")

        # Cria a definição
        defn = group.Definitions.get_Item(PARAM_NAME)
        if defn is None:
            try:
                # Revit 2023+
                from Autodesk.Revit.DB import SpecTypeId
                opts = ExternalDefinitionCreationOptions(PARAM_NAME, SpecTypeId.String.Text)
            except Exception:
                # Revit 2021 e anteriores
                from Autodesk.Revit.DB import ParameterType as _PT
                opts = ExternalDefinitionCreationOptions(PARAM_NAME, _PT.Text)
            opts.Visible = True
            defn = group.Definitions.Create(opts)

        # Vincula como parâmetro de instância
        binding = app.Create.NewInstanceBinding(cat_set)
        binding_map = doc.ParameterBindings
        binding_map.Insert(defn, binding)

        _param_ensured = True
    except Exception as ex:
        print(u"Aviso: não foi possível criar o parâmetro '{}': {}".format(PARAM_NAME, ex))
    finally:
        # Restaura o arquivo de parâmetros compartilhados original
        try:
            app.SharedParametersFilename = original_spf or ""
        except Exception:
            pass
        # Remove o arquivo temporário
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def write_location_to_element(element, room_data):
    """Grava número + nome do ambiente, combinados, em um único parâmetro de ambiente.
    Exemplo de valor: '1.01 - Recepção'"""
    value = u"{} - {}".format(room_data["number"], room_data["name"])
    try:
        p = element.LookupParameter(PARAM_NAME)
        if p and not p.IsReadOnly and p.StorageType == StorageType.String:
            p.Set(value)
            return True
    except Exception:
        pass
    return False


# ─────────── LINHA DE RESULTADO ───────────
class ResultRow(object):
    """Linha com binding para o DataGrid de resultados."""
    def __init__(self, elem_id, elem_name, category, room_num, room_name, level, status):
        self.ElementId = str(elem_id)
        self.ElementName = elem_name
        self.Category = category
        self.RoomNumber = room_num
        self.RoomName = room_name
        self.Level = level
        self.Status = status


# ─────────── INTERFACE ───────────
_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="UNIBIM Smart Location – Detecção de ambientes do link"
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

        <!-- Título -->
        <TextBlock Grid.Row="0" Text="SMART LOCATION" FontSize="16"
                   FontWeight="Bold" Foreground="#2C3E50" Margin="0,0,0,4"/>
        <TextBlock Grid.Row="1" TextWrapping="Wrap" Foreground="#666"
                   Text="Selecione um link para importar os seus ambientes (Rooms) e localizar os elementos do modelo atual."/>

        <!-- Seleção do link -->
        <StackPanel Grid.Row="2" Margin="0,10,0,0">
            <TextBlock Text="1 – Selecione o link:" Style="{StaticResource Header}"/>
            <ComboBox x:Name="cb_links" Height="28" Margin="0,0,0,4"/>
            <TextBlock x:Name="tb_rooms_info" Text="" Foreground="#888" FontSize="11"/>
        </StackPanel>

        <!-- Seleção das categorias -->
        <StackPanel Grid.Row="3" Margin="0,8,0,0">
            <TextBlock Text="2 – Categorias a processar:" Style="{StaticResource Header}"/>
            <WrapPanel Margin="0,2,0,0">
                <CheckBox x:Name="chk_mep" Content="MEP" IsChecked="True" Margin="0,0,14,0"/>
                <CheckBox x:Name="chk_arch" Content="Arquitetura" IsChecked="False" Margin="0,0,14,0"/>
                <CheckBox x:Name="chk_selection" Content="Somente a seleção atual" IsChecked="False"/>
            </WrapPanel>
        </StackPanel>

        <!-- DataGrid de resultados -->
        <DataGrid Grid.Row="4" x:Name="dg_results"
                  AutoGenerateColumns="False"
                  IsReadOnly="True"
                  CanUserSortColumns="True"
                  Margin="0,10,0,0"
                  HeadersVisibility="Column"
                  GridLinesVisibility="Horizontal"
                  AlternatingRowBackground="#F8F8F8">
            <DataGrid.Columns>
                <DataGridTextColumn Header="ID do elemento" Binding="{Binding ElementId}" Width="100"/>
                <DataGridTextColumn Header="Elemento" Binding="{Binding ElementName}" Width="180"/>
                <DataGridTextColumn Header="Categoria" Binding="{Binding Category}" Width="130"/>
                <DataGridTextColumn Header="Nº ambiente" Binding="{Binding RoomNumber}" Width="80"/>
                <DataGridTextColumn Header="Nome do ambiente" Binding="{Binding RoomName}" Width="150"/>
                <DataGridTextColumn Header="Nível" Binding="{Binding Level}" Width="100"/>
                <DataGridTextColumn Header="Status" Binding="{Binding Status}" Width="110"/>
            </DataGrid.Columns>
        </DataGrid>

        <!-- Estatísticas -->
        <TextBlock Grid.Row="5" x:Name="tb_stats" Text="" Foreground="#444"
                   FontSize="11" Margin="0,6,0,0"/>

        <!-- Botões -->
        <StackPanel Grid.Row="6" Orientation="Horizontal"
                    HorizontalAlignment="Right" Margin="0,10,0,0">
            <Button x:Name="btn_detect" Content="Detectar" Width="110" Height="32"
                    Background="#2C3E50" Foreground="White" FontWeight="SemiBold"
                    Margin="0,0,8,0"/>
            <Button x:Name="btn_write" Content="Gravar" Width="110" Height="32"
                    Background="#27AE60" Foreground="White" FontWeight="SemiBold"
                    IsEnabled="False" Margin="0,0,8,0"/>
            <Button x:Name="btn_export" Content="Exportar CSV" Width="110" Height="32"
                    IsEnabled="False" Margin="0,0,8,0"/>
            <Button x:Name="btn_close" Content="Fechar" Width="90" Height="32"/>
        </StackPanel>
    </Grid>
</Window>
"""


class SmartLocationUI(object):
    def __init__(self):
        stream = MemoryStream(Encoding.UTF8.GetBytes(_XAML))
        self.window = XamlReader.Load(stream)

        # controles
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

        # preenchimento
        for name in sorted(_link_dict.keys()):
            self.cb_links.Items.Add(name)

        # estado
        self._rooms_data = []
        self._results = []  # lista de ResultRow
        self._location_map = {}  # element_id -> room_data

        # eventos
        self.cb_links.SelectionChanged += self._on_link_changed
        self.btn_detect.Click += self._on_detect
        self.btn_write.Click += self._on_write
        self.btn_export.Click += self._on_export
        self.btn_close.Click += self._on_close

    # --- eventos ---
    def _on_link_changed(self, sender, args):
        name = self.cb_links.SelectedItem
        if not name:
            return
        link_inst = _link_dict[str(name)]
        self._rooms_data = get_rooms_from_link(link_inst)
        count = len(self._rooms_data)
        self.tb_rooms_info.Text = "{} ambientes encontrados no link.".format(count)
        if count == 0:
            forms.alert(
                u"O link selecionado não tem ambientes válidos (posicionados/delimitados).",
                title="Smart Location",
            )

    def _collect_elements(self):
        """Coleta os elementos do hospedeiro a processar, conforme as caixas marcadas na interface."""
        if self.chk_selection.IsChecked:
            sel_ids = uidoc.Selection.GetElementIds()
            return [doc.GetElement(eid) for eid in sel_ids if doc.GetElement(eid)]

        cats = []
        if self.chk_mep.IsChecked:
            cats.extend(_MEP_CATEGORIES)
        if self.chk_arch.IsChecked:
            cats.extend(_ARCH_CATEGORIES)

        if not cats:
            forms.alert("Selecione pelo menos uma categoria.", title="Smart Location")
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
                "Selecione um link com ambientes antes de detectar.",
                title="Smart Location",
            )
            return

        elements = self._collect_elements()
        if not elements:
            forms.alert(
                "Nenhum elemento encontrado para processar.",
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
                        "Encontrado",
                    )
                    self._location_map[str(eid)] = room
                    found += 1
                else:
                    row = ResultRow(
                        eid, elem_name, cat_name,
                        "-", "-", "-", u"Não encontrado",
                    )
                    not_found += 1
                self._results.append(row)
            except Exception as ex:
                pass

        elapsed = time.time() - t0
        speed = len(elements) / elapsed if elapsed > 0 else 0

        self.dg_results.ItemsSource = self._results
        total_label = "{total} elementos | {ok} localizados | {nf} sem ambiente | " \
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

        # Determina quais categorias precisam do parâmetro
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

        with revit.Transaction(u"Smart Location – Gravar ambiente"):
            # Cria o parâmetro, se ainda não existir
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
            u"Gravação concluída!\n\n"
            u"  Gravados: {}\n  Ignorados: {}\n\n"
            u"Parâmetro: '{}'".format(
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
            u"ID do elemento;Elemento;Categoria;Nº ambiente;Nome do ambiente;Nível;Status"
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


# ─────────── PONTO DE ENTRADA ───────────
ui = SmartLocationUI()
ui.show()
