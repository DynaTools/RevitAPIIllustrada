# -*- coding: utf-8 -*-
"""Change Level.

Reposiciona um nivel para uma nova cota e leva TODOS os seus elementos
junto (rigid shift): cada elemento mantem o seu offset relativo ao nivel
e desce/sobe exatamente o mesmo delta.

Substitui a rotina manual do Dynamo (criar nivel-falso -> mover elementos
para ele -> mover o nivel vazio -> trazer os elementos de volta). Aqui isto
e' feito num unico passo, sem nivel-falso: mover a cota do nivel pela API
ja arrasta TODO elemento associado a ele (por parametro de nivel ou pela
propriedade LevelId), preservando os offsets. Tudo dentro de UMA transacao
= um unico Ctrl+Z.

Fluxo:
    1. Escolher o nivel de origem (dropdown) e a nova cota.
    2. "Analisar" (nao altera nada) classifica os elementos afetados e
       avisa sobre os que vao deformar (uma ponta presa a outro nivel).
    3. "Aplicar" executa numa unica transacao.

Author: Paulo Giavoni
"""

__title__ = "Change\nLevel"
__doc__ = (
    "Reposiciona um nivel para uma nova cota e move todos os seus "
    "elementos junto (rigid shift), mantendo os offsets. Automatiza a "
    "rotina do nivel-falso do Dynamo num unico clique."
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
# UNIT HELPERS  (Revit interno = pes; projeto do usuario = metros)
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
    """Aceita virgula ou ponto como separador decimal."""
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
# PARAMETROS DE NIVEL  (variam por categoria)
# ============================================================
# Params que POSICIONAM o elemento em relacao a um nivel. Setar a cota do
# nivel referenciado por um destes move o elemento. Nao inclui o "Schedule
# Level" (INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM) porque este nao reposiciona.

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
    "WALL_HEIGHT_TYPE",          # topo "Up to level" da parede
    "FAMILY_TOP_LEVEL_PARAM",
    "ROOF_UPTO_LEVEL_PARAM",
    "STAIRS_TOP_LEVEL_PARAM",
    "RBS_END_LEVEL_PARAM",
]

BASE_LEVEL_BIPS = [b for b in (_bip(n) for n in _BASE_LEVEL_NAMES) if b is not None]
TOP_LEVEL_BIPS = [b for b in (_bip(n) for n in _TOP_LEVEL_NAMES) if b is not None]
ALL_LEVEL_BIPS = BASE_LEVEL_BIPS + TOP_LEVEL_BIPS


def get_positional_level_params(el):
    """Lista (parametro, level_id) de todos os params de nivel POSICIONAIS
    do elemento (base e topo).

    Inclui params somente-leitura de proposito: um elemento com vinculo de
    nivel read-only ainda SEGUE o nivel quando este se move, entao deve ser
    classificado como 'segue o nivel' e nunca transladado (evita mover em
    dobro). Nao escrevemos nestes params - so os lemos para classificar."""
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
# ANALISE (somente leitura)
# ============================================================
# Ao setar level.Elevation, o Revit move automaticamente TODO elemento
# associado ao nivel (por parametro posicional de nivel ou pela propriedade
# LevelId) - paredes, pisos, pilares, mobiliario, ambientes, hospedados, etc.
# Nao ha translacao manual: so identificamos o que sera afetado e avisamos
# sobre os que vao deformar (uma ponta presa a outro nivel).

class Analysis(object):
    """Resultado da classificacao dos elementos afetados."""

    def __init__(self):
        self.clean_move = []     # movem-se por inteiro com o nivel
        self.deform = []         # movem uma ponta; a outra fica noutro nivel
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
    """Classifica todos os elementos de modelo em relacao ao nivel origem.
    Nao altera o modelo."""
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

            # Tambem conta como associado quando a propriedade LevelId aponta
            # para o nivel (ambientes, espacos e hospedados sem param gravavel).
            if not on_source and not params:
                if get_level_id_property(el) == source_id:
                    on_source = True

            if not on_source:
                continue

            if other_ref:
                res.deform.append(el.Id)   # outra ponta presa a outro nivel
            else:
                res.clean_move.append(el.Id)
            res.tally(el)
        except Exception:
            # Elemento problematico: ignora com seguranca na analise.
            continue

    return res


# ============================================================
# EXECUCAO (transacao)
# ============================================================

def apply_change(document, level, new_elev_ft, analysis):
    """Move o nivel para a nova cota. Todos os elementos associados seguem
    automaticamente (mantendo os offsets). Retorna dict com o relatorio."""
    delta_ft = new_elev_ft - level.Elevation
    report = {
        "moved": analysis.n_move,
        "deform": len(analysis.deform),
        "unpinned_level": False,
        "delta_m": to_m(delta_ft),
    }

    t = Transaction(document, "Change Level")
    t.Start()
    try:
        # Despina o nivel se preciso (a cota nao muda em nivel pinado).
        if level.Pinned:
            level.Pinned = False
            report["unpinned_level"] = True

        # Move a cota do nivel. Todos os elementos vinculados (clean_move e
        # deform) seguem automaticamente, mantendo os offsets = rigid shift.
        level.Elevation = new_elev_ft

        t.Commit()
    except Exception as ex:
        if t.GetStatus() == TransactionStatus.Started:
            t.RollBack()
        raise ex

    return report


# ============================================================
# XAML UI
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
      Reposiciona um nivel para uma nova cota e leva todos os seus
      elementos junto (mantendo os offsets). Clique em Analisar para ver o
      que sera afetado, depois em Aplicar.
    </TextBlock>

    <GroupBox Grid.Row="1" Header="Nivel de origem"
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

    <GroupBox Grid.Row="3" Header="Analise"
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
# UI CLASS
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

        self.levels = []          # list of Level, ordenados por cota
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
        # Qualquer mudanca na cota invalida a analise anterior.
        self._reset_analysis()
        self._update_delta()

    def on_analyze(self, sender, args):
        lv = self._selected_level()
        if lv is None:
            forms.alert("Selecione um nivel de origem.", title="Change Level")
            return
        new_m = parse_number(self.txt_new.Text)
        if new_m is None:
            forms.alert("Nova cota invalida.", title="Change Level")
            return

        with forms.ProgressBar(title="Analisando elementos...", indeterminate=True):
            self.analysis = analyze(doc, lv.Id)

        self._show_report(lv, new_m, self.analysis)
        self.grp_report.Visibility = Visibility.Visible
        self.btn_apply.IsEnabled = self.analysis.n_move > 0

    def _show_report(self, lv, new_m, a):
        delta = new_m - to_m(lv.Elevation)
        lines = []
        lines.append(u"Nivel:  {}".format(lv.Name))
        lines.append(u"Cota:   {} m  ->  {:.3f} m   (delta {:+.3f} m)".format(
            fmt_m(lv.Elevation), new_m, delta))
        lines.append(u"")
        lines.append(u"Elementos que se MOVEM: {}".format(a.n_move))
        lines.append(u"  - por inteiro com o nivel:  {}".format(
            len(a.clean_move)))
        if a.deform:
            lines.append(u"  - ATENCAO, deformam:        {}  "
                         u"(outra ponta noutro nivel)".format(len(a.deform)))
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
            forms.alert("A nova cota e' igual a atual.", title="Change Level")
            return

        msg = (u"Mover o nivel '{}' para {:.3f} m (delta {:+.3f} m)?\n\n"
               u"{} elemento(s) serao movidos.").format(
            lv.Name, new_m, delta, self.analysis.n_move)
        if self.analysis.deform:
            msg += (u"\n\nATENCAO: {} elemento(s) tem a outra ponta vinculada "
                    u"a outro nivel e VAO DEFORMAR.").format(
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
        # Recarrega niveis (cotas mudaram) e reinicia a analise.
        self._populate()
        self._reset_analysis()

    def _report_result(self, lv, report):
        output.print_md("## Change Level - concluido")
        output.print_md("**Nivel:** {}".format(lv.Name))
        output.print_md("**Delta:** {:+.3f} m".format(report["delta_m"]))
        output.print_md(
            "- Elementos movidos com o nivel: **{}**".format(report["moved"]))
        if report["deform"]:
            output.print_md(
                "- Elementos deformados (outra ponta noutro nivel): "
                "**{}**".format(report["deform"]))
        if report["unpinned_level"]:
            output.print_md("- _O nivel estava pinado e foi despinado._")
        forms.alert(
            u"Concluido.\n\n{} elemento(s) movidos com o nivel '{}'.".format(
                report["moved"], lv.Name),
            title="Change Level")

    def on_close(self, sender, args):
        self.window.Close()

    def show(self):
        self.window.ShowDialog()


# ============================================================
# ENTRY POINT
# ============================================================

if not list(FilteredElementCollector(doc).OfClass(Level)):
    forms.alert("O modelo nao tem niveis.", title="Change Level")
else:
    ChangeLevelUI().show()
