# -*- coding: utf-8 -*-
"""Exclui parâmetros das famílias carregadas no projeto."""

__title__ = "Delete\nFamily Params"
__doc__ = (
    u"Procura parâmetros específicos nas famílias carregadas e os exclui "
    u"de forma seletiva. Análise em uma única passada, seleção linha a "
    u"linha e exclusão em lote com acompanhamento do progresso."
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
    FilteredElementCollector,
    Family,
    FamilySource,
    Transaction,
    IFamilyLoadOptions,
)
from pyrevit import revit, forms, script

from collections import OrderedDict

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()
logger = script.get_logger()


# ============================================================
# Auxiliar de recarga de famílias  (compatível com IronPython + CPython)
# ============================================================

class OverwriteLoadOptions(IFamilyLoadOptions):
    """Sempre sobrescreve parâmetros e valores na recarga."""

    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        try:
            overwriteParameterValues.Value = True   # IronPython StrongBox
        except (AttributeError, TypeError):
            pass
        return True

    def OnSharedFamilyFound(
        self, sharedFamily, familyInUse, source, overwriteParameterValues
    ):
        try:
            source.Value = FamilySource.Family
            overwriteParameterValues.Value = True
        except (AttributeError, TypeError):
            pass
        return True


# ============================================================
# Lógica principal
# ============================================================

def get_all_families():
    """Devolve um dict ordenado {family_name: Family} das famílias editáveis."""
    items = []
    for fam in FilteredElementCollector(doc).OfClass(Family):
        if fam.IsEditable:
            try:
                items.append((fam.Name, fam))
            except Exception:
                pass
    items.sort(key=lambda x: x[0])
    return OrderedDict(items)


def get_family_category(family):
    """Devolve o nome da categoria de uma família, ou uma string vazia."""
    try:
        cat = family.FamilyCategory
        return cat.Name if cat else ""
    except Exception:
        return ""


def scan_families_for_params(param_names, families_dict, progress_cb=None):
    """Abre cada família UMA vez e procura TODOS os parâmetros pedidos.

    Devolve uma lista de (param_name, family_name, category, Family).
    """
    param_set = set(param_names)
    results = []
    total = len(families_dict)

    for idx, (fam_name, fam) in enumerate(families_dict.items()):
        if progress_cb:
            progress_cb(idx, total, fam_name)

        fam_doc = None
        try:
            fam_doc = doc.EditFamily(fam)
            if fam_doc is None:
                continue

            fam_params = set()
            for p in fam_doc.FamilyManager.Parameters:
                try:
                    fam_params.add(p.Definition.Name)
                except Exception:
                    pass

            category = get_family_category(fam)
            matched = param_set & fam_params

            for pname in param_names:           # mantém a ordem do usuário
                if pname in matched:
                    results.append((pname, fam_name, category, fam))
        except Exception:
            pass
        finally:
            if fam_doc is not None:
                try:
                    fam_doc.Close(False)
                except Exception:
                    pass

    if progress_cb:
        progress_cb(total, total, "")

    return results


def delete_params_from_family(family, param_names):
    """Abre a família UMA vez, exclui todos os parâmetros listados e recarrega.

    Devolve um dict {param_name: (ok, mensagem)}.
    """
    results = {}
    fam_doc = None
    try:
        fam_doc = doc.EditFamily(family)
        if fam_doc is None:
            for pn in param_names:
                results[pn] = (False, u"Não foi possível abrir a família")
            return results

        fm = fam_doc.FamilyManager

        # Associa os nomes dos parâmetros aos objetos FamilyParameter
        param_map = {}
        for p in fm.Parameters:
            try:
                name = p.Definition.Name
                if name in param_names:
                    param_map[name] = p
            except Exception:
                pass

        # Exclui em uma única transação
        t = Transaction(fam_doc, u"Excluir parâmetros")
        t.Start()
        any_deleted = False

        for pn in param_names:
            if pn not in param_map:
                results[pn] = (False, u"Parâmetro não encontrado")
                continue
            try:
                fm.RemoveParameter(param_map[pn])
                results[pn] = (True, "OK")
                any_deleted = True
            except Exception as e:
                results[pn] = (False, str(e))

        if any_deleted:
            try:
                t.Commit()
            except Exception as e:
                try:
                    t.RollBack()
                except Exception:
                    pass
                for pn in param_names:
                    if results.get(pn, (False,))[0]:
                        results[pn] = (False, u"Falha no commit: " + str(e))
                fam_doc.Close(False)
                return results
        else:
            try:
                t.RollBack()
            except Exception:
                pass
            fam_doc.Close(False)
            return results

        # Recarrega no projeto
        try:
            fam_doc.LoadFamily(doc, OverwriteLoadOptions())
        except Exception as e:
            for pn in param_names:
                if results.get(pn, (False,))[0]:
                    results[pn] = (
                        True,
                        u"Excluído, mas a recarga falhou: " + str(e),
                    )

        fam_doc.Close(False)
        return results

    except Exception as e:
        if fam_doc is not None:
            try:
                fam_doc.Close(False)
            except Exception:
                pass
        for pn in param_names:
            if pn not in results:
                results[pn] = (False, str(e))
        return results


# ============================================================
# Interface XAML
# ============================================================

XAML_STR = u"""\
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Excluir parâmetros de famílias"
    Width="880" Height="720"
    WindowStartupLocation="CenterScreen"
    ResizeMode="CanResizeWithGrip"
    MinWidth="650" MinHeight="500">
  <Grid Margin="15">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <!-- Linha 0: Entrada -->
    <GroupBox Grid.Row="0" Margin="0,0,0,8" Padding="8"
              BorderBrush="#3498DB" BorderThickness="1.5">
      <GroupBox.Header>
        <TextBlock Text=" Nomes dos parâmetros a excluir "
                   FontWeight="Bold" FontSize="13"/>
      </GroupBox.Header>
      <StackPanel>
        <TextBlock Text="Digite os nomes dos parâmetros (um por linha):"
                   FontSize="11.5" Margin="0,0,0,4" Foreground="#555"/>
        <TextBox x:Name="txt_params" AcceptsReturn="True"
                 Height="80" TextWrapping="Wrap"
                 VerticalScrollBarVisibility="Auto"
                 FontFamily="Consolas" FontSize="12"
                 Padding="4"/>
        <StackPanel Orientation="Horizontal" Margin="0,8,0,0">
          <Button x:Name="btn_scan" Content="Analisar famílias"
                  Width="130" Height="32" FontSize="12"
                  FontWeight="Bold" Margin="0,0,8,0"
                  Background="#2980B9" Foreground="White" Cursor="Hand"/>
        </StackPanel>
      </StackPanel>
    </GroupBox>

    <!-- Linha 1: Barra de progresso -->
    <StackPanel Grid.Row="1" x:Name="pnl_progress"
                Visibility="Collapsed" Margin="0,0,0,8">
      <TextBlock x:Name="txt_progress" FontSize="11"
                 Foreground="#555" Margin="0,0,0,3"/>
      <ProgressBar x:Name="progress_bar" Height="20"
                   Minimum="0" Maximum="100"
                   Foreground="#2ECC71" Background="#ECF0F1"/>
    </StackPanel>

    <!-- Linha 2: Resultados -->
    <GroupBox Grid.Row="2" Margin="0,0,0,8" Padding="0"
              x:Name="grp_results" Visibility="Collapsed"
              BorderBrush="#2ECC71" BorderThickness="1.5">
      <GroupBox.Header>
        <TextBlock Text=" Resultados da análise " FontWeight="Bold" FontSize="13"/>
      </GroupBox.Header>
      <DockPanel Margin="8">
        <StackPanel DockPanel.Dock="Top" Orientation="Horizontal"
                    Margin="0,0,0,6">
          <Button x:Name="btn_select_all" Content="Selecionar tudo"
                  Width="105" Height="26" FontSize="11"
                  Margin="0,0,6,0" Background="#ECF0F1" Cursor="Hand"/>
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
                Binding="{Binding param_name}" Width="*" MinWidth="150"/>
            <DataGridTextColumn Header="Família"
                Binding="{Binding family_name}" Width="*" MinWidth="180"/>
            <DataGridTextColumn Header="Categoria"
                Binding="{Binding category}" Width="120"/>
            <DataGridTextColumn Header="Status"
                Binding="{Binding status}" Width="110"/>
          </DataGrid.Columns>
        </DataGrid>
      </DockPanel>
    </GroupBox>

    <!-- Linha 3: Mostrar/ocultar o registro -->
    <StackPanel Grid.Row="3" x:Name="pnl_log_toggle"
                Visibility="Collapsed">
      <Button x:Name="btn_toggle_log"
              Content="&#x25B8; Mostrar registro"
              HorizontalAlignment="Left" Height="24" FontSize="11"
              Background="Transparent" BorderThickness="0"
              Cursor="Hand" Foreground="#555" Margin="0,0,0,4"/>
    </StackPanel>

    <!-- Linha 4: Registro (recolhido por padrão) -->
    <GroupBox Grid.Row="4" x:Name="grp_log" Visibility="Collapsed"
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

    <!-- Linha 5: Resumo + botões de ação -->
    <DockPanel Grid.Row="5" Margin="0,4,0,0">
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

class ScanRow(object):
    """Objeto de linha para o DataGrid de resultados."""

    def __init__(self, param, family, category,
                 family_obj=None, status=u"Encontrado"):
        self.is_selected = (status == u"Encontrado")
        self.param_name = param
        self.family_name = family
        self.category = category
        self.status = status
        self._family_obj = family_obj       # referência interna


# ============================================================
# CLASSE DA INTERFACE
# ============================================================

class DeleteFamilyParamsUI(object):
    def __init__(self):
        xaml_bytes = Encoding.UTF8.GetBytes(XAML_STR)
        stream = MemoryStream(xaml_bytes)
        self.window = XamlReader.Load(stream)
        stream.Close()

        # --- controles ---
        self.txt_params       = self.window.FindName("txt_params")
        self.btn_scan         = self.window.FindName("btn_scan")
        self.pnl_progress     = self.window.FindName("pnl_progress")
        self.txt_progress     = self.window.FindName("txt_progress")
        self.progress_bar     = self.window.FindName("progress_bar")
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

        # --- eventos ---
        self.btn_scan.Click         += self.on_scan
        self.btn_delete.Click       += self.on_delete
        self.btn_close.Click        += self.on_close
        self.btn_select_all.Click   += self.on_select_all
        self.btn_deselect_all.Click += self.on_deselect_all
        self.btn_toggle_log.Click   += self.on_toggle_log
        self.dg_results.PreviewMouseLeftButtonUp += self._on_grid_click

        # --- estado ---
        self.rows = []
        self.families_dict = None
        self._log_visible = False

    # --------------------------------------------------------
    # Auxiliares
    # --------------------------------------------------------

    def _get_param_names(self):
        """Lê os nomes dos parâmetros da caixa de texto."""
        raw = self.txt_params.Text or ""
        names = []
        for line in raw.split("\n"):
            line = line.strip().strip("\r")
            if line:
                names.append(line)
        return names

    def _log(self, msg):
        self.txt_log.Text += msg + "\n"
        self.txt_log.ScrollToEnd()

    def _force_ui_update(self):
        """Bombeia o dispatcher do WPF para atualizar o visual (DoEvents)."""
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
        """Atualiza o contador '3 de 5 selecionados' e o botão Excluir."""
        if not self.rows:
            self.txt_selection_info.Text = ""
            self.btn_delete.IsEnabled = False
            return
        actionable = [r for r in self.rows if r.status not in
                      (u"Não encontrado", u"Excluído", u"FALHOU")]
        selected = sum(1 for r in actionable if r.is_selected)
        total = len(actionable)
        self.txt_selection_info.Text = (
            u"{} de {} selecionado(s)".format(selected, total)
        )
        self.btn_delete.IsEnabled = selected > 0

    # --------------------------------------------------------
    # Eventos
    # --------------------------------------------------------

    def _on_grid_click(self, sender, args):
        """Depois de um clique em uma caixa de seleção, atualiza a informação de seleção."""
        Dispatcher.CurrentDispatcher.BeginInvoke(
            DispatcherPriority.Input,
            System.Action(self._update_selection_info),
        )

    def on_select_all(self, sender, args):
        for row in self.rows:
            if row.status == u"Encontrado":
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
        param_names = self._get_param_names()
        if not param_names:
            forms.alert(u"Digite pelo menos um nome de parâmetro.",
                        title=u"Análise")
            return

        # Reinicia a interface
        self.txt_log.Text = ""
        self.pnl_log_toggle.Visibility = Visibility.Visible
        self.btn_scan.IsEnabled = False
        self.btn_delete.IsEnabled = False
        self._force_ui_update()

        self._log(u"Carregando as famílias editáveis...")
        if self.families_dict is None:
            self.families_dict = get_all_families()

        total_fam = len(self.families_dict)
        self._log(u"{} famílias editáveis encontradas.".format(total_fam))
        self._log(u"Procurando {} parâmetro(s)...".format(
            len(param_names)
        ))
        self._log("")

        # --- Análise em uma única passada, com progresso ---
        def progress_cb(current, total, fam_name):
            if fam_name:
                self._set_progress(
                    current, total,
                    u"Analisando {}/{}: {}".format(
                        current + 1, total, fam_name
                    ),
                )
            else:
                self._set_progress(total, total, u"Análise concluída.")

        scan_results = scan_families_for_params(
            param_names, self.families_dict, progress_cb
        )

        # Monta as linhas
        self.rows = []
        found_params = set()
        for pname, fname, category, fam in scan_results:
            self.rows.append(
                ScanRow(pname, fname, category, fam, u"Encontrado")
            )
            found_params.add(pname)
            self._log(u"  '{}' encontrado em '{}' [{}]".format(
                pname, fname, category
            ))

        for pname in param_names:
            if pname not in found_params:
                self.rows.append(
                    ScanRow(pname, "-", "-", None, u"Não encontrado")
                )
                self._log(u"  '{}' não encontrado em nenhuma família.".format(
                    pname
                ))

        # Atualiza a grade
        self.dg_results.ItemsSource = self.rows
        self.grp_results.Visibility = Visibility.Visible
        self._update_selection_info()

        found_count = sum(1 for r in self.rows if r.status == u"Encontrado")
        self.txt_summary.Text = (
            u"{} parâmetro(s) analisado(s)  |  "
            u"{} ocorrência(s) encontrada(s)".format(len(param_names), found_count)
        )

        self.btn_scan.IsEnabled = True
        self._log("")
        self._log(u"Análise terminada. {} ocorrência(s) encontrada(s).".format(
            found_count
        ))

    def on_delete(self, sender, args):
        # Garante que o binding foi confirmado
        try:
            self.dg_results.CommitEdit()
            self.dg_results.CommitEdit()
        except Exception:
            pass

        selected = [
            r for r in self.rows
            if r.is_selected and r.status == u"Encontrado"
        ]
        if not selected:
            forms.alert(u"Nenhum item selecionado.", title=u"Excluir")
            return

        # Agrupa por família (abre cada família uma vez só)
        family_groups = OrderedDict()
        for row in selected:
            fn = row.family_name
            if fn not in family_groups:
                family_groups[fn] = {
                    "params": [],
                    "family_obj": row._family_obj,
                    "rows": [],
                }
            family_groups[fn]["params"].append(row.param_name)
            family_groups[fn]["rows"].append(row)

        msg = (
            u"Excluir {} parâmetro(s) de {} família(s)?\n\n"
            u"Cada família será editada e recarregada.\n"
            u"Isto não se desfaz com facilidade."
        ).format(len(selected), len(family_groups))

        if not forms.alert(msg, title=u"Confirmar exclusão",
                           yes=True, no=True):
            return

        self.btn_delete.IsEnabled = False
        self.btn_scan.IsEnabled = False
        self._log("")
        self._log(u"Iniciando a exclusão...")

        success = 0
        failed = 0
        total_families = len(family_groups)

        for idx, (fam_name, group) in enumerate(family_groups.items()):
            self._set_progress(
                idx, total_families,
                u"Excluindo de {}/{}: {}".format(
                    idx + 1, total_families, fam_name
                ),
            )
            self._log(u"  Família '{}': excluindo {}...".format(
                fam_name,
                ", ".join("'{}'".format(p) for p in group["params"]),
            ))

            results = delete_params_from_family(
                group["family_obj"], group["params"]
            )

            for row in group["rows"]:
                ok, msg_result = results.get(
                    row.param_name, (False, u"Desconhecido")
                )
                if ok:
                    row.status = u"Excluído"
                    row.is_selected = False
                    success += 1
                    self._log(u"    '{}': OK".format(row.param_name))
                else:
                    row.status = u"FALHOU"
                    failed += 1
                    self._log(u"    '{}': FALHOU - {}".format(
                        row.param_name, msg_result
                    ))

        self._set_progress(
            total_families, total_families, u"Exclusão concluída."
        )

        self.dg_results.Items.Refresh()
        self._update_selection_info()

        self.txt_summary.Text = (
            u"Pronto  |  {} excluído(s)  |  {} com falha".format(success, failed)
        )
        self._log("")
        self._log(u"Pronto. {} excluído(s), {} com falha.".format(success, failed))

        self.btn_scan.IsEnabled = True
        # Zera o cache para a próxima análise enxergar as mudanças
        self.families_dict = None

    def on_close(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()


# ============================================================
# PONTO DE ENTRADA
# ============================================================

ui = DeleteFamilyParamsUI()
ui.show()
