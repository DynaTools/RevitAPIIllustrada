# -*- coding: utf-8 -*-
"""Change Level.

Reposiciona um nível para uma nova cota e leva TODOS os seus elementos
junto (deslocamento rígido): cada elemento mantém o seu offset relativo ao
nível e desce/sobe exatamente o mesmo delta.

Substitui a rotina manual do Dynamo (criar um nível falso -> mover os
elementos para ele -> mover o nível vazio -> trazer os elementos de volta).
Aqui isso é feito em um único passo, sem nível falso: mover a cota do nível
pela API já arrasta TODO elemento associado a ele (por parâmetro de nível ou
pela propriedade LevelId), preservando os offsets. Tudo dentro de UMA
transação = um único Ctrl+Z.

Fluxo:
    1. Escolher o nível de origem (lista suspensa) e a nova cota.
    2. "Analisar" (não altera nada) classifica os elementos afetados e
       avisa sobre os que vão deformar (uma ponta presa a outro nível).
    3. "Aplicar" executa em uma única transação.

Autor: Paulo Giavoni
"""

__title__ = "Change\nLevel"
__doc__ = (
    "Reposiciona um nível para uma nova cota e move todos os seus "
    "elementos junto (deslocamento rígido), mantendo os offsets. Automatiza "
    "a rotina do nível falso do Dynamo em um único clique."
)
__author__ = "Paulo Giavoni"

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    Level,
    Grid,
    ElementId,
    BuiltInParameter,
    StorageType,
    CategoryType,
    Transaction,
    TransactionStatus,
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

INVALID = ElementId.InvalidElementId


# ============================================================
# AUXILIARES DE UNIDADE  (Revit interno = pés; projeto do usuário = metros)
# ============================================================

FEET_TO_M = 0.3048

try:
    from Autodesk.Revit.DB import UnitTypeId

    def to_m(feet):
        return UnitUtils.ConvertFromInternalUnits(feet, UnitTypeId.Meters)

    def to_ft(meters):
        return UnitUtils.ConvertToInternalUnits(meters, UnitTypeId.Meters)
except Exception:
    def to_m(feet):
        return feet * FEET_TO_M

    def to_ft(meters):
        return meters / FEET_TO_M


def fmt_m(feet):
    return "{:.3f}".format(to_m(feet))


def parse_number(text):
    """Aceita vírgula ou ponto como separador decimal."""
    if text is None:
        return None
    t = text.strip().replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except (ValueError, TypeError):
        return None


# ============================================================
# PARÂMETROS DE NÍVEL  (variam por categoria)
# ============================================================
# Parâmetros que POSICIONAM o elemento em relação a um nível. Alterar a cota
# do nível referenciado por um destes move o elemento. Não inclui o "Schedule
# Level" (INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM) porque este não reposiciona.

def _bip(name):
    try:
        return getattr(BuiltInParameter, name)
    except AttributeError:
        return None


_BASE_LEVEL_NAMES = [
    "WALL_BASE_CONSTRAINT",
    "FAMILY_BASE_LEVEL_PARAM",
    "FAMILY_LEVEL_PARAM",
    "LEVEL_PARAM",
    "ROOF_BASE_LEVEL_PARAM",
    "STAIRS_BASE_LEVEL_PARAM",
    "RBS_START_LEVEL_PARAM",
]
_TOP_LEVEL_NAMES = [
    "WALL_HEIGHT_TYPE",          # topo "Up to level" (até o nível) da parede
    "FAMILY_TOP_LEVEL_PARAM",
    "ROOF_UPTO_LEVEL_PARAM",
    "STAIRS_TOP_LEVEL_PARAM",
    "RBS_END_LEVEL_PARAM",
]

BASE_LEVEL_BIPS = [b for b in (_bip(n) for n in _BASE_LEVEL_NAMES) if b is not None]
TOP_LEVEL_BIPS = [b for b in (_bip(n) for n in _TOP_LEVEL_NAMES) if b is not None]
ALL_LEVEL_BIPS = BASE_LEVEL_BIPS + TOP_LEVEL_BIPS


def get_positional_level_params(el):
    """Lista (parâmetro, level_id) de todos os parâmetros de nível
    POSICIONAIS do elemento (base e topo).

    Inclui de propósito os parâmetros somente leitura: um elemento com vínculo
    de nível read-only ainda SEGUE o nível quando este se move, então deve ser
    classificado como 'segue o nível' e nunca transladado (evita mover em
    dobro). Não gravamos nesses parâmetros; só os lemos para classificar."""
    found = []
    for bip in ALL_LEVEL_BIPS:
        try:
            p = el.get_Parameter(bip)
        except Exception:
            p = None
        if p is None:
            continue
        try:
            if p.StorageType != StorageType.ElementId:
                continue
            v = p.AsElementId()
        except Exception:
            continue
        if v is not None and v != INVALID:
            found.append((p, v))
    return found


def get_level_id_property(el):
    try:
        lid = el.LevelId          # Revit 2022+
        if lid is not None and lid != INVALID:
            return lid
    except Exception:
        pass
    return None


# ============================================================
# ANÁLISE (somente leitura)
# ============================================================
# Ao alterar level.Elevation, o Revit move automaticamente TODO elemento
# associado ao nível (por parâmetro posicional de nível ou pela propriedade
# LevelId) - paredes, pisos, pilares, mobiliário, ambientes, hospedados etc.
# Não há translação manual: só identificamos o que será afetado e avisamos
# sobre os que vão deformar (uma ponta presa a outro nível).

class Analysis(object):
    """Resultado da classificação dos elementos afetados."""

    def __init__(self):
        self.clean_move = []     # movem-se por inteiro com o nível
        self.deform = []         # movem uma ponta; a outra fica em outro nível
        self.cat_counts = {}     # categoria -> contagem (do que se move)

    def tally(self, el):
        try:
            cat = el.Category
            name = cat.Name if cat is not None else "(sem categoria)"
        except Exception:
            name = "(sem categoria)"
        self.cat_counts[name] = self.cat_counts.get(name, 0) + 1

    @property
    def n_move(self):
        return len(self.clean_move) + len(self.deform)


def analyze(document, source_id):
    """Classifica todos os elementos de modelo em relação ao nível de origem.
    Não altera o modelo."""
    res = Analysis()

    collector = (
        FilteredElementCollector(document)
        .WhereElementIsNotElementType()
        .WhereElementIsViewIndependent()
    )

    for el in collector:
        try:
            if el.Id == source_id:
                continue
            if isinstance(el, (Level, Grid)):
                continue
            cat = el.Category
            if cat is None or cat.CategoryType != CategoryType.Model:
                continue

            params = get_positional_level_params(el)
            on_source = any(v == source_id for (_, v) in params)
            other_ref = any(v != source_id for (_, v) in params)

            # Também conta como associado quando a propriedade LevelId aponta
            # para o nível (ambientes, espaços e hospedados sem parâmetro gravável).
            if not on_source and not params:
                if get_level_id_property(el) == source_id:
                    on_source = True

            if not on_source:
                continue

            if other_ref:
                res.deform.append(el.Id)   # outra ponta presa a outro nível
            else:
                res.clean_move.append(el.Id)
            res.tally(el)
        except Exception:
            # Elemento problemático: ignorado com segurança na análise.
            continue

    return res


# ============================================================
# EXECUÇÃO (transação)
# ============================================================

def apply_change(document, level, new_elev_ft, analysis):
    """Move o nível para a nova cota. Todos os elementos associados seguem
    automaticamente (mantendo os offsets). Retorna um dict com o relatório."""
    delta_ft = new_elev_ft - level.Elevation
    report = {
        "moved": analysis.n_move,
        "deform": len(analysis.deform),
        "unpinned_level": False,
        "delta_m": to_m(delta_ft),
    }

    t = Transaction(document, u"Alterar nível")
    t.Start()
    try:
        # Desafixa o nível se preciso (a cota não muda em nível fixado).
        if level.Pinned:
            level.Pinned = False
            report["unpinned_level"] = True

        # Move a cota do nível. Todos os elementos vinculados (clean_move e
        # deform) seguem automaticamente, mantendo os offsets = deslocamento rígido.
        level.Elevation = new_elev_ft

        t.Commit()
    except Exception as ex:
        if t.GetStatus() == TransactionStatus.Started:
            t.RollBack()
        raise ex

    return report


# ============================================================
# INTERFACE XAML
# ============================================================

XAML_STR = u"""\
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Change Level"
    Width="560" SizeToContent="Height"
    WindowStartupLocation="CenterScreen"
    ResizeMode="NoResize">
  <Grid Margin="15">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <TextBlock Grid.Row="0" TextWrapping="Wrap" Foreground="#555"
               Margin="0,0,0,12">
      Reposiciona um nível para uma nova cota e leva todos os seus
      elementos junto (mantendo os offsets). Clique em Analisar para ver o
      que será afetado e depois em Aplicar.
    </TextBlock>

    <GroupBox Grid.Row="1" Header="Nível de origem"
              Margin="0,0,0,10" FontWeight="Bold">
      <StackPanel Margin="8">
        <ComboBox x:Name="cb_source" Height="28" FontWeight="Normal"/>
        <TextBlock x:Name="lbl_current" FontWeight="Normal"
                   Foreground="#555" Margin="2,6,0,0"/>
      </StackPanel>
    </GroupBox>

    <GroupBox Grid.Row="2" Header="Nova cota (m)"
              Margin="0,0,0,10" FontWeight="Bold">
      <StackPanel Orientation="Horizontal" Margin="8">
        <TextBox x:Name="txt_new" Width="140" Height="28"
                 FontWeight="Normal" VerticalContentAlignment="Center"/>
        <TextBlock x:Name="lbl_delta" FontWeight="Normal"
                   Foreground="#555" VerticalAlignment="Center"
                   Margin="12,0,0,0"/>
      </StackPanel>
    </GroupBox>

    <GroupBox Grid.Row="3" Header="Análise"
              Margin="0,0,0,10" FontWeight="Bold"
              Visibility="Collapsed" x:Name="grp_report">
      <ScrollViewer MaxHeight="240" VerticalScrollBarVisibility="Auto">
        <TextBlock x:Name="txt_report" FontWeight="Normal"
                   FontFamily="Consolas" FontSize="11" Margin="8"
                   TextWrapping="Wrap"/>
      </ScrollViewer>
    </GroupBox>

    <StackPanel Grid.Row="4" Orientation="Horizontal"
                HorizontalAlignment="Right">
      <Button x:Name="btn_analyze" Content="Analisar"
              Width="100" Height="32" Margin="0,0,10,0" FontSize="12"
              FontWeight="Bold" Background="#2980B9" Foreground="White"/>
      <Button x:Name="btn_apply" Content="Aplicar"
              Width="100" Height="32" Margin="0,0,10,0" FontSize="12"
              FontWeight="Bold" Background="#27AE60" Foreground="White"
              IsEnabled="False"/>
      <Button x:Name="btn_close" Content="Fechar"
              Width="90" Height="32" FontSize="12"/>
    </StackPanel>
  </Grid>
</Window>"""


# ============================================================
# CLASSE DA INTERFACE
# ============================================================

class ChangeLevelUI(object):
    def __init__(self):
        xaml_bytes = Encoding.UTF8.GetBytes(XAML_STR)
        stream = MemoryStream(xaml_bytes)
        self.window = XamlReader.Load(stream)
        stream.Close()

        self.cb_source = self.window.FindName("cb_source")
        self.lbl_current = self.window.FindName("lbl_current")
        self.txt_new = self.window.FindName("txt_new")
        self.lbl_delta = self.window.FindName("lbl_delta")
        self.grp_report = self.window.FindName("grp_report")
        self.txt_report = self.window.FindName("txt_report")
        self.btn_analyze = self.window.FindName("btn_analyze")
        self.btn_apply = self.window.FindName("btn_apply")
        self.btn_close = self.window.FindName("btn_close")

        self.btn_analyze.Click += self.on_analyze
        self.btn_apply.Click += self.on_apply
        self.btn_close.Click += self.on_close
        self.cb_source.SelectionChanged += self.on_source_changed
        self.txt_new.TextChanged += self.on_new_changed

        self.levels = []          # lista de Level, ordenados por cota
        self.analysis = None
        self._populate()

    # ---------------------------------------------------------

    def _populate(self):
        self.levels = list(
            FilteredElementCollector(doc).OfClass(Level).ToElements()
        )
        self.levels.sort(key=lambda l: l.Elevation)
        self.cb_source.Items.Clear()
        for lv in self.levels:
            self.cb_source.Items.Add(
                u"{}   ({} m)".format(lv.Name, fmt_m(lv.Elevation))
            )
        if self.levels:
            self.cb_source.SelectedIndex = 0

    def _selected_level(self):
        idx = self.cb_source.SelectedIndex
        if idx < 0 or idx >= len(self.levels):
            return None
        return self.levels[idx]

    def _reset_analysis(self):
        self.analysis = None
        self.btn_apply.IsEnabled = False
        self.grp_report.Visibility = Visibility.Collapsed

    def _update_delta(self):
        lv = self._selected_level()
        new_m = parse_number(self.txt_new.Text)
        if lv is None or new_m is None:
            self.lbl_delta.Text = ""
            return
        delta = new_m - to_m(lv.Elevation)
        arrow = u"↑" if delta > 0 else (u"↓" if delta < 0 else u"=")
        self.lbl_delta.Text = u"{} delta {:+.3f} m".format(arrow, delta)

    # ---------------------------------------------------------

    def on_source_changed(self, sender, args):
        lv = self._selected_level()
        if lv is not None:
            self.lbl_current.Text = u"Cota atual: {} m".format(
                fmt_m(lv.Elevation)
            )
            self.txt_new.Text = fmt_m(lv.Elevation)
        self._reset_analysis()
        self._update_delta()

    def on_new_changed(self, sender, args):
        # Qualquer mudança na cota invalida a análise anterior.
        self._reset_analysis()
        self._update_delta()

    def on_analyze(self, sender, args):
        lv = self._selected_level()
        if lv is None:
            forms.alert(u"Selecione um nível de origem.", title="Change Level")
            return
        new_m = parse_number(self.txt_new.Text)
        if new_m is None:
            forms.alert(u"Nova cota inválida.", title="Change Level")
            return

        with forms.ProgressBar(title="Analisando elementos...", indeterminate=True):
            self.analysis = analyze(doc, lv.Id)

        self._show_report(lv, new_m, self.analysis)
        self.grp_report.Visibility = Visibility.Visible
        self.btn_apply.IsEnabled = self.analysis.n_move > 0

    def _show_report(self, lv, new_m, a):
        delta = new_m - to_m(lv.Elevation)
        lines = []
        lines.append(u"Nível:  {}".format(lv.Name))
        lines.append(u"Cota:   {} m  ->  {:.3f} m   (delta {:+.3f} m)".format(
            fmt_m(lv.Elevation), new_m, delta))
        lines.append(u"")
        lines.append(u"Elementos que se MOVEM: {}".format(a.n_move))
        lines.append(u"  - por inteiro com o nível:  {}".format(
            len(a.clean_move)))
        if a.deform:
            lines.append(u"  - ATENÇÃO, deformam:        {}  "
                         u"(outra ponta em outro nível)".format(len(a.deform)))
        if a.cat_counts:
            lines.append(u"")
            lines.append(u"Por categoria:")
            for name, n in sorted(a.cat_counts.items(),
                                  key=lambda kv: -kv[1]):
                lines.append(u"  {:>4}  {}".format(n, name))
        self.txt_report.Text = u"\n".join(lines)

    def on_apply(self, sender, args):
        lv = self._selected_level()
        new_m = parse_number(self.txt_new.Text)
        if lv is None or new_m is None or self.analysis is None:
            forms.alert("Analise primeiro.", title="Change Level")
            return

        delta = new_m - to_m(lv.Elevation)
        if abs(delta) < 1e-6:
            forms.alert(u"A nova cota é igual à atual.", title="Change Level")
            return

        msg = (u"Mover o nível '{}' para {:.3f} m (delta {:+.3f} m)?\n\n"
               u"{} elemento(s) serão movido(s).").format(
            lv.Name, new_m, delta, self.analysis.n_move)
        if self.analysis.deform:
            msg += (u"\n\nATENÇÃO: {} elemento(s) têm a outra ponta vinculada "
                    u"a outro nível e VÃO DEFORMAR.").format(
                len(self.analysis.deform))
        if not forms.alert(msg, title="Confirmar", yes=True, no=True):
            return

        new_elev_ft = to_ft(new_m)
        try:
            with forms.ProgressBar(title="Aplicando...", indeterminate=True):
                report = apply_change(doc, lv, new_elev_ft, self.analysis)
        except Exception as ex:
            forms.alert(u"Erro ao aplicar:\n{}".format(ex),
                        title="Change Level")
            return

        self._report_result(lv, report)
        # Recarrega os níveis (as cotas mudaram) e reinicia a análise.
        self._populate()
        self._reset_analysis()

    def _report_result(self, lv, report):
        output.print_md(u"## Change Level - concluído")
        output.print_md(u"**Nível:** {}".format(lv.Name))
        output.print_md("**Delta:** {:+.3f} m".format(report["delta_m"]))
        output.print_md(
            u"- Elementos movidos com o nível: **{}**".format(report["moved"]))
        if report["deform"]:
            output.print_md(
                u"- Elementos deformados (outra ponta em outro nível): "
                u"**{}**".format(report["deform"]))
        if report["unpinned_level"]:
            output.print_md(u"- _O nível estava fixado e foi desafixado._")
        forms.alert(
            u"Concluído.\n\n{} elemento(s) movido(s) com o nível '{}'.".format(
                report["moved"], lv.Name),
            title="Change Level")

    def on_close(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()


# ============================================================
# PONTO DE ENTRADA
# ============================================================

if not list(FilteredElementCollector(doc).OfClass(Level)):
    forms.alert(u"O modelo não tem níveis.", title="Change Level")
else:
    ChangeLevelUI().show()
