# -*- coding: utf-8 -*-
"""Gerenciador de parâmetros do projeto: lista todos e exclui os que você quiser."""

__title__ = "Parameter\nManager"
__doc__ = (
    u"Analisa todos os parâmetros do projeto (compartilhados ou não, "
    u"preenchidos ou vazios) e mostra estatísticas de uso. Filtre, ordene, "
    u"selecione e exclua quaisquer parâmetros em um único lote."
)
__author__ = "Paulo Giavoni"

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

import System
from System.IO import MemoryStream
from System.Text import Encoding
from System.Windows import Visibility
from System.Windows.Markup import XamlReader
from System.Windows.Threading import (
    Dispatcher,
    DispatcherFrame,
    DispatcherPriority,
)

from Autodesk.Revit.DB import (
    ElementId,
    ElementCategoryFilter,
    ElementFilter,
    FilteredElementCollector,
    InstanceBinding,
    LogicalOrFilter,
    ParameterElement,
    SharedParameterElement,
    StorageType,
    Transaction,
)
from pyrevit import revit, forms, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()
logger = script.get_logger()


# ============================================================
# Lógica principal
# ============================================================

def _param_has_value(p):
    """Devolve True se o parâmetro tem um valor não padrão / não vazio."""
    try:
        if p is None or not p.HasValue:
            return False
        st = p.StorageType
        if st == StorageType.String:
            v = p.AsString()
            return v is not None and v.strip() != ""
        if st == StorageType.ElementId:
            eid = p.AsElementId()
            return eid is not None and eid != ElementId.InvalidElementId
        if st == StorageType.Integer:
            return True
        if st == StorageType.Double:
            return True
        return False
    except Exception:
        return False


def get_project_parameters():
    """Devolve uma lista de dicts que descrevem cada vínculo de parâmetro do projeto."""
    items = []

    pe_map = {}
    for pe in FilteredElementCollector(doc).OfClass(ParameterElement):
        try:
            pe_map[pe.GetDefinition().Name] = pe
        except Exception:
            pass
    for spe in FilteredElementCollector(doc).OfClass(SharedParameterElement):
        try:
            pe_map[spe.GetDefinition().Name] = spe
        except Exception:
            pass

    bindings = doc.ParameterBindings
    it = bindings.ForwardIterator()
    it.Reset()
    while it.MoveNext():
        definition = it.Key
        binding = it.Current
        try:
            cats = [c for c in binding.Categories]
        except Exception:
            cats = []

        pe = pe_map.get(definition.Name)
        is_shared = isinstance(pe, SharedParameterElement)

        try:
            st_label = str(definition.ParameterType)
        except Exception:
            st_label = "-"

        items.append({
            "name": definition.Name,
            "definition": definition,
            "binding": binding,
            "categories": cats,
            "is_instance": isinstance(binding, InstanceBinding),
            "is_shared": is_shared,
            "param_element": pe,
            "type_label": st_label,
        })

    items.sort(key=lambda x: x["name"].lower())
    return items


def _collect_elements_for_categories(categories, is_instance):
    """Devolve um iterável de elementos (instâncias ou tipos) das categorias dadas."""
    if not categories:
        return []

    cat_filters = []
    for cat in categories:
        try:
            cat_filters.append(ElementCategoryFilter(cat.Id))
        except Exception:
            pass
    if not cat_filters:
        return []

    if len(cat_filters) == 1:
        combined = cat_filters[0]
    else:
        flist = System.Collections.Generic.List[ElementFilter](cat_filters)
        combined = LogicalOrFilter(flist)

    collector = FilteredElementCollector(doc).WherePasses(combined)
    if is_instance:
        return collector.WhereElementIsNotElementType().ToElements()
    return collector.WhereElementIsElementType().ToElements()


def scan_all_parameters(progress_cb=None):
    """Analisa todos os parâmetros do projeto e calcula as estatísticas de uso."""
    params = get_project_parameters()
    total = len(params)
    results = []

    for idx, info in enumerate(params):
        if progress_cb:
            progress_cb(idx, total, info["name"])

        elements = _collect_elements_for_categories(
            info["categories"], info["is_instance"]
        )
        element_count = 0
        filled_count = 0

        for el in elements:
            element_count += 1
            try:
                p = el.LookupParameter(info["name"])
                if _param_has_value(p):
                    filled_count += 1
            except Exception:
                pass

        cat_names = ", ".join(
            sorted(c.Name for c in info["categories"] if c is not None)
        )
        info["category_names"] = cat_names or "-"
        info["element_count"] = element_count
        info["filled_count"] = filled_count
        results.append(info)

    if progress_cb:
        progress_cb(total, total, "")

    return results


def delete_project_parameter(item):
    """Exclui o elemento do parâmetro. Devolve (ok, mensagem)."""
    pe = item.get("param_element")
    if pe is None:
        try:
            doc.ParameterBindings.Remove(item["definition"])
            return (True, u"Vínculo removido (nenhum elemento a excluir)")
        except Exception as e:
            return (False, u"Falha ao remover: " + str(e))
    try:
        doc.Delete(pe.Id)
        return (True, "OK")
    except Exception as e:
        try:
            doc.ParameterBindings.Remove(item["definition"])
            return (True, u"Vínculo removido: " + str(e))
        except Exception as e2:
            return (False, str(e2))


# ============================================================
# Interface XAML
# ============================================================

XAML_STR = u"""\
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Gerenciador de parâmetros do projeto"
    Width="980" Height="740"
    WindowStartupLocation="CenterScreen"
    ResizeMode="CanResizeWithGrip"
    MinWidth="700" MinHeight="500">
  <Grid Margin="15">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Linha 0: Análise -->
    <GroupBox Grid.Row="0" Margin="0,0,0,8" Padding="8"
              BorderBrush="#3498DB" BorderThickness="1.5">
      <GroupBox.Header>
        <TextBlock Text=" Parâmetros do projeto "
                   FontWeight="Bold" FontSize="13"/>
      </GroupBox.Header>
      <StackPanel>
        <TextBlock TextWrapping="Wrap" FontSize="11.5"
                   Foreground="#555" Margin="0,0,0,6"
                   Text="Analisa todos os vínculos de parâmetros do projeto (compartilhados ou não) e mostra quantos elementos têm um valor preenchido. Selecione as linhas que quiser para excluir em lote."/>
        <StackPanel Orientation="Horizontal" Margin="0,4,0,0">
          <Button x:Name="btn_scan" Content="Analisar parâmetros"
                  Width="150" Height="32" FontSize="12"
                  FontWeight="Bold" Margin="0,0,8,0"
                  Background="#2980B9" Foreground="White" Cursor="Hand"/>
        </StackPanel>
      </StackPanel>
    </GroupBox>

    <!-- Linha 1: Progresso -->
    <StackPanel Grid.Row="1" x:Name="pnl_progress"
                Visibility="Collapsed" Margin="0,0,0,8">
      <TextBlock x:Name="txt_progress" FontSize="11"
                 Foreground="#555" Margin="0,0,0,3"/>
      <ProgressBar x:Name="progress_bar" Height="20"
                   Minimum="0" Maximum="100"
                   Foreground="#2ECC71" Background="#ECF0F1"/>
    </StackPanel>

    <!-- Linha 2: Filtros -->
    <Grid Grid.Row="2" x:Name="pnl_filters" Visibility="Collapsed"
          Margin="0,0,0,6">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <TextBox x:Name="txt_filter" Grid.Column="0"
               Margin="0,0,8,0" Padding="4"
               VerticalContentAlignment="Center"
               ToolTip="Filtrar por nome do parâmetro, categoria, tipo..."/>
      <ComboBox x:Name="cmb_kind" Grid.Column="1" Width="135"
                Margin="0,0,6,0" SelectedIndex="0">
        <ComboBoxItem Content="Todas as origens"/>
        <ComboBoxItem Content="Compartilhados"/>
        <ComboBoxItem Content="De projeto"/>
      </ComboBox>
      <ComboBox x:Name="cmb_binding" Grid.Column="2" Width="135"
                Margin="0,0,6,0" SelectedIndex="0">
        <ComboBoxItem Content="Todos os vínculos"/>
        <ComboBoxItem Content="Instância"/>
        <ComboBoxItem Content="Tipo"/>
      </ComboBox>
      <ComboBox x:Name="cmb_usage" Grid.Column="3" Width="135"
                Margin="0,0,6,0" SelectedIndex="0">
        <ComboBoxItem Content="Qualquer uso"/>
        <ComboBoxItem Content="Só vazios"/>
        <ComboBoxItem Content="Só preenchidos"/>
      </ComboBox>
      <Button x:Name="btn_clear_filter" Grid.Column="4" Content="Limpar"
              Width="60" Height="26" FontSize="11"
              Background="#ECF0F1" Cursor="Hand"/>
    </Grid>

    <!-- Linha 3: Resultados -->
    <GroupBox Grid.Row="3" Margin="0,0,0,8" Padding="0"
              x:Name="grp_results" Visibility="Collapsed"
              BorderBrush="#2ECC71" BorderThickness="1.5">
      <GroupBox.Header>
        <TextBlock Text=" Parâmetros " FontWeight="Bold" FontSize="13"/>
      </GroupBox.Header>
      <DockPanel Margin="8">
        <StackPanel DockPanel.Dock="Top" Orientation="Horizontal"
                    Margin="0,0,0,6">
          <Button x:Name="btn_select_all" Content="Selecionar tudo"
                  Width="105" Height="26" FontSize="11"
                  Margin="0,0,6,0" Background="#ECF0F1" Cursor="Hand"
                  ToolTip="Seleciona todas as linhas visíveis"/>
          <Button x:Name="btn_deselect_all" Content="Desmarcar tudo"
                  Width="105" Height="26" FontSize="11"
                  Margin="0,0,12,0" Background="#ECF0F1" Cursor="Hand"/>
          <TextBlock x:Name="txt_selection_info" FontSize="11"
                     Foreground="#777" VerticalAlignment="Center"/>
        </StackPanel>
        <DataGrid x:Name="dg_results"
                  AutoGenerateColumns="False"
                  IsReadOnly="True"
                  CanUserSortColumns="True"
                  CanUserResizeColumns="True"
                  HeadersVisibility="Column"
                  AlternatingRowBackground="#F7F9FB"
                  RowBackground="White"
                  GridLinesVisibility="Horizontal"
                  BorderThickness="1" BorderBrush="#CCC"
                  SelectionMode="Extended"
                  FontSize="12">
          <DataGrid.Columns>
            <DataGridTemplateColumn Header="&#x2713;" Width="40"
                SortMemberPath="is_selected">
              <DataGridTemplateColumn.CellTemplate>
                <DataTemplate>
                  <CheckBox IsChecked="{Binding is_selected,
                              Mode=TwoWay,
                              UpdateSourceTrigger=PropertyChanged}"
                            HorizontalAlignment="Center"
                            VerticalAlignment="Center"/>
                </DataTemplate>
              </DataGridTemplateColumn.CellTemplate>
            </DataGridTemplateColumn>
            <DataGridTextColumn Header="Parâmetro"
                Binding="{Binding param_name}" Width="*" MinWidth="180"/>
            <DataGridTextColumn Header="Origem"
                Binding="{Binding kind}" Width="100"/>
            <DataGridTextColumn Header="Vínculo"
                Binding="{Binding binding_kind}" Width="80"/>
            <DataGridTextColumn Header="Tipo de dado"
                Binding="{Binding type_label}" Width="120"/>
            <DataGridTextColumn Header="Categorias"
                Binding="{Binding category_names}" Width="*" MinWidth="160"/>
            <DataGridTextColumn Header="Preenchidos"
                Binding="{Binding filled_count}" Width="85"/>
            <DataGridTextColumn Header="Total"
                Binding="{Binding element_count}" Width="60"/>
            <DataGridTextColumn Header="Uso"
                Binding="{Binding usage_label}" Width="120"/>
            <DataGridTextColumn Header="Status"
                Binding="{Binding status}" Width="90"/>
          </DataGrid.Columns>
        </DataGrid>
      </DockPanel>
    </GroupBox>

    <!-- Linha 4: Mostrar/ocultar o registro -->
    <StackPanel Grid.Row="4" x:Name="pnl_log_toggle"
                Visibility="Collapsed">
      <Button x:Name="btn_toggle_log"
              Content="&#x25B8; Mostrar registro"
              HorizontalAlignment="Left" Height="24" FontSize="11"
              Background="Transparent" BorderThickness="0"
              Cursor="Hand" Foreground="#555" Margin="0,0,0,4"/>
    </StackPanel>

    <!-- Linha 5: Registro -->
    <GroupBox Grid.Row="5" x:Name="grp_log" Visibility="Collapsed"
              Margin="0,0,0,8" BorderBrush="#95A5A6" BorderThickness="1">
      <GroupBox.Header>
        <TextBlock Text=" Registro " FontWeight="Bold" FontSize="12"/>
      </GroupBox.Header>
      <TextBox x:Name="txt_log" IsReadOnly="True"
               MaxHeight="150" TextWrapping="Wrap"
               VerticalScrollBarVisibility="Auto"
               FontFamily="Consolas" FontSize="10.5"
               Margin="6" Foreground="#333"/>
    </GroupBox>

    <!-- Linha 6: Resumo + ações -->
    <DockPanel Grid.Row="6" Margin="0,4,0,0">
      <StackPanel DockPanel.Dock="Right" Orientation="Horizontal"
                  VerticalAlignment="Center">
        <Button x:Name="btn_delete" Content="Excluir selecionados"
                Width="165" Height="34" FontSize="12.5"
                FontWeight="Bold" IsEnabled="False"
                Margin="0,0,10,0" Cursor="Hand"
                Background="#E74C3C" Foreground="White"/>
        <Button x:Name="btn_close" Content="Fechar"
                Width="90" Height="34" FontSize="12" Cursor="Hand"/>
      </StackPanel>
      <TextBlock x:Name="txt_summary" FontSize="11.5"
                 Foreground="#555" VerticalAlignment="Center"
                 TextWrapping="Wrap"/>
    </DockPanel>
  </Grid>
</Window>"""


# ============================================================
# LINHA DE DADOS
# ============================================================

class ParamRow(object):
    """Objeto de linha para o DataGrid."""

    def __init__(self, item):
        self.is_selected = False
        self.param_name = item["name"]
        self.kind = u"Compartilhado" if item["is_shared"] else u"Projeto"
        self.binding_kind = u"Instância" if item["is_instance"] else u"Tipo"
        self.type_label = item.get("type_label", "-")
        self.category_names = item["category_names"]
        self.filled_count = item["filled_count"]
        self.element_count = item["element_count"]
        if item["element_count"] == 0:
            self.usage_label = u"Sem elementos"
        elif item["filled_count"] == 0:
            self.usage_label = u"Vazio"
        elif item["filled_count"] >= item["element_count"]:
            self.usage_label = u"Todos preenchidos"
        else:
            self.usage_label = u"Parcial"
        self.status = "-"
        self._item = item


# ============================================================
# CLASSE DA INTERFACE
# ============================================================

class ParameterManagerUI(object):
    def __init__(self):
        xaml_bytes = Encoding.UTF8.GetBytes(XAML_STR)
        stream = MemoryStream(xaml_bytes)
        self.window = XamlReader.Load(stream)
        stream.Close()

        self.btn_scan         = self.window.FindName("btn_scan")
        self.pnl_progress     = self.window.FindName("pnl_progress")
        self.txt_progress     = self.window.FindName("txt_progress")
        self.progress_bar     = self.window.FindName("progress_bar")
        self.pnl_filters      = self.window.FindName("pnl_filters")
        self.txt_filter       = self.window.FindName("txt_filter")
        self.cmb_kind         = self.window.FindName("cmb_kind")
        self.cmb_binding      = self.window.FindName("cmb_binding")
        self.cmb_usage        = self.window.FindName("cmb_usage")
        self.btn_clear_filter = self.window.FindName("btn_clear_filter")
        self.grp_results      = self.window.FindName("grp_results")
        self.dg_results       = self.window.FindName("dg_results")
        self.btn_select_all   = self.window.FindName("btn_select_all")
        self.btn_deselect_all = self.window.FindName("btn_deselect_all")
        self.txt_selection_info = self.window.FindName("txt_selection_info")
        self.pnl_log_toggle   = self.window.FindName("pnl_log_toggle")
        self.btn_toggle_log   = self.window.FindName("btn_toggle_log")
        self.grp_log          = self.window.FindName("grp_log")
        self.txt_log          = self.window.FindName("txt_log")
        self.txt_summary      = self.window.FindName("txt_summary")
        self.btn_delete       = self.window.FindName("btn_delete")
        self.btn_close        = self.window.FindName("btn_close")

        self.btn_scan.Click            += self.on_scan
        self.btn_delete.Click          += self.on_delete
        self.btn_close.Click           += self.on_close
        self.btn_select_all.Click      += self.on_select_all
        self.btn_deselect_all.Click    += self.on_deselect_all
        self.btn_toggle_log.Click      += self.on_toggle_log
        self.btn_clear_filter.Click    += self.on_clear_filter
        self.txt_filter.TextChanged       += self._on_filter_changed
        self.cmb_kind.SelectionChanged    += self._on_filter_changed
        self.cmb_binding.SelectionChanged += self._on_filter_changed
        self.cmb_usage.SelectionChanged   += self._on_filter_changed
        self.dg_results.PreviewMouseLeftButtonUp += self._on_grid_click

        self.all_rows = []      # conjunto completo
        self.rows = []          # mostradas agora (filtradas)
        self._log_visible = False

    # --------------------------------------------------------
    # Auxiliares
    # --------------------------------------------------------

    def _log(self, msg):
        self.txt_log.Text += msg + "\n"
        self.txt_log.ScrollToEnd()

    def _force_ui_update(self):
        frame = DispatcherFrame()

        def stop_frame():
            frame.Continue = False

        Dispatcher.CurrentDispatcher.BeginInvoke(
            DispatcherPriority.Background,
            System.Action(stop_frame),
        )
        Dispatcher.PushFrame(frame)

    def _set_progress(self, current, total, text=""):
        self.pnl_progress.Visibility = Visibility.Visible
        if total > 0:
            self.progress_bar.Value = int(
                (current / float(total)) * 100
            )
        self.txt_progress.Text = text
        self._force_ui_update()

    def _update_selection_info(self):
        if not self.all_rows:
            self.txt_selection_info.Text = ""
            self.btn_delete.IsEnabled = False
            return
        actionable = [r for r in self.all_rows
                      if r.status not in (u"Excluído", u"FALHOU")]
        selected = sum(1 for r in actionable if r.is_selected)
        visible = len(self.rows)
        total = len(self.all_rows)
        self.txt_selection_info.Text = (
            u"{} selecionado(s)  |  mostrando {} de {}".format(
                selected, visible, total
            )
        )
        self.btn_delete.IsEnabled = selected > 0

    def _apply_filter(self):
        if not self.all_rows:
            self.rows = []
            self.dg_results.ItemsSource = self.rows
            self._update_selection_info()
            return

        text = (self.txt_filter.Text or "").strip().lower()
        kind = self.cmb_kind.SelectedIndex          # 0 todos, 1 compartilhado, 2 projeto
        binding = self.cmb_binding.SelectedIndex    # 0 todos, 1 instância, 2 tipo
        usage = self.cmb_usage.SelectedIndex        # 0 todos, 1 vazio, 2 preenchido

        filtered = []
        for r in self.all_rows:
            if kind == 1 and r.kind != u"Compartilhado":
                continue
            if kind == 2 and r.kind != u"Projeto":
                continue
            if binding == 1 and r.binding_kind != u"Instância":
                continue
            if binding == 2 and r.binding_kind != u"Tipo":
                continue
            if usage == 1 and r.filled_count > 0:
                continue
            if usage == 2 and r.filled_count == 0:
                continue
            if text:
                hay = u" ".join([
                    r.param_name or u"",
                    r.kind or u"",
                    r.binding_kind or u"",
                    r.type_label or u"",
                    r.category_names or u"",
                    r.usage_label or u"",
                ]).lower()
                if text not in hay:
                    continue
            filtered.append(r)

        self.rows = filtered
        self.dg_results.ItemsSource = self.rows
        self._update_selection_info()

    # --------------------------------------------------------
    # Eventos
    # --------------------------------------------------------

    def _on_grid_click(self, sender, args):
        Dispatcher.CurrentDispatcher.BeginInvoke(
            DispatcherPriority.Input,
            System.Action(self._update_selection_info),
        )

    def _on_filter_changed(self, sender, args):
        self._apply_filter()

    def on_clear_filter(self, sender, args):
        self.txt_filter.Text = ""
        self.cmb_kind.SelectedIndex = 0
        self.cmb_binding.SelectedIndex = 0
        self.cmb_usage.SelectedIndex = 0
        self._apply_filter()

    def on_select_all(self, sender, args):
        for row in self.rows:
            if row.status not in (u"Excluído", u"FALHOU"):
                row.is_selected = True
        self.dg_results.Items.Refresh()
        self._update_selection_info()

    def on_deselect_all(self, sender, args):
        for row in self.rows:
            row.is_selected = False
        self.dg_results.Items.Refresh()
        self._update_selection_info()

    def on_toggle_log(self, sender, args):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.grp_log.Visibility = Visibility.Visible
            self.btn_toggle_log.Content = u"\u25BE Ocultar registro"
        else:
            self.grp_log.Visibility = Visibility.Collapsed
            self.btn_toggle_log.Content = u"\u25B8 Mostrar registro"

    def on_scan(self, sender, args):
        self.txt_log.Text = ""
        self.pnl_log_toggle.Visibility = Visibility.Visible
        self.btn_scan.IsEnabled = False
        self.btn_delete.IsEnabled = False
        self._force_ui_update()

        self._log(u"Analisando os parâmetros do projeto...")

        def progress_cb(current, total, name):
            if name:
                self._set_progress(
                    current, total,
                    u"Verificando {}/{}: {}".format(current + 1, total, name),
                )
            else:
                self._set_progress(total, total, u"Análise concluída.")

        try:
            items = scan_all_parameters(progress_cb)
        except Exception as e:
            self._log(u"ERRO: " + str(e))
            forms.alert(u"A análise falhou:\n" + str(e), title=u"Erro")
            self.btn_scan.IsEnabled = True
            return

        self.all_rows = [ParamRow(item) for item in items]
        self.pnl_filters.Visibility = Visibility.Visible
        self.grp_results.Visibility = Visibility.Visible
        self._apply_filter()

        empty = sum(1 for r in self.all_rows if r.filled_count == 0)
        partial = sum(1 for r in self.all_rows
                      if 0 < r.filled_count < r.element_count)
        full = sum(1 for r in self.all_rows
                   if r.element_count > 0
                   and r.filled_count >= r.element_count)

        self.txt_summary.Text = (
            u"{} parâmetros  |  {} vazios  |  {} parciais  |  {} todos preenchidos"
        ).format(len(self.all_rows), empty, partial, full)

        for r in self.all_rows:
            self._log(u"  '{}' [{}, {}]  {}/{} preenchidos".format(
                r.param_name, r.kind, r.binding_kind,
                r.filled_count, r.element_count,
            ))

        if not self.all_rows:
            self._log(u"Nenhum parâmetro de projeto encontrado.")

        self.btn_scan.IsEnabled = True
        self._log("")
        self._log(u"Pronto. {} parâmetros analisados.".format(len(self.all_rows)))

    def on_delete(self, sender, args):
        try:
            self.dg_results.CommitEdit()
            self.dg_results.CommitEdit()
        except Exception:
            pass

        selected = [
            r for r in self.all_rows
            if r.is_selected and r.status not in (u"Excluído", u"FALHOU")
        ]
        if not selected:
            forms.alert(u"Nenhum item selecionado.", title=u"Excluir")
            return

        with_data = [r for r in selected if r.filled_count > 0]
        warn = ""
        if with_data:
            warn = (
                u"\n\nATENÇÃO: {} destes parâmetros têm dados preenchidos "
                u"em elementos. Excluí-los apagará esses dados."
            ).format(len(with_data))

        msg = (
            u"Excluir {} parâmetro(s) de projeto do modelo?\n\n"
            u"Isto remove a definição e o vínculo do parâmetro.{}"
        ).format(len(selected), warn)
        if not forms.alert(msg, title=u"Confirmar exclusão",
                           yes=True, no=True):
            return

        self.btn_delete.IsEnabled = False
        self.btn_scan.IsEnabled = False
        self._log("")
        self._log(u"Excluindo parâmetros...")

        success = 0
        failed = 0
        total = len(selected)

        t = Transaction(doc, u"Excluir parâmetros do projeto")
        t.Start()
        try:
            for idx, row in enumerate(selected):
                self._set_progress(
                    idx, total,
                    u"Excluindo {}/{}: {}".format(
                        idx + 1, total, row.param_name
                    ),
                )
                ok, message = delete_project_parameter(row._item)
                if ok:
                    row.status = u"Excluído"
                    row.is_selected = False
                    success += 1
                    self._log(u"  '{}': OK".format(row.param_name))
                else:
                    row.status = u"FALHOU"
                    failed += 1
                    self._log(u"  '{}': FALHOU - {}".format(
                        row.param_name, message
                    ))
            t.Commit()
        except Exception as e:
            try:
                t.RollBack()
            except Exception:
                pass
            self._log(u"ERRO: transação revertida - " + str(e))
            forms.alert(u"A exclusão falhou:\n" + str(e), title=u"Erro")
            self.btn_scan.IsEnabled = True
            return

        self._set_progress(total, total, u"Exclusão concluída.")
        self.dg_results.Items.Refresh()
        self._update_selection_info()

        self.txt_summary.Text = (
            u"Pronto  |  {} excluído(s)  |  {} com falha".format(success, failed)
        )
        self._log("")
        self._log(u"Pronto. {} excluído(s), {} com falha.".format(success, failed))

        self.btn_scan.IsEnabled = True

    def on_close(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()


# ============================================================
# PONTO DE ENTRADA
# ============================================================

ui = ParameterManagerUI()
ui.show()
