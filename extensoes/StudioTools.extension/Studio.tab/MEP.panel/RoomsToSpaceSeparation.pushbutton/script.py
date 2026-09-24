# -*- coding: utf-8 -*-
"""Cria linhas de separação de espaço com os ambientes de um link.

Fluxo
-----
1. Escolha um link de arquitetura carregado (automático quando só há um).
2. Cada ambiente (Room) posicionado é lido do link e os seus laços de contorno
   são extraídos na face de acabamento das paredes (o mesmo contorno que você
   vê no ambiente), incluindo os laços internos (ilhas / furos).
3. Cada nível do link é associado ao nível mais próximo do hospedeiro,
   comparando elevações em coordenadas do hospedeiro (a transformação do link
   é aplicada e usa-se ``ProjectElevation``, para que uma base de elevação
   Compartilhada não quebre a correspondência).
4. O usuário escolhe quais níveis do hospedeiro processar e se quer só
   acrescentar as linhas que faltam ou antes substituir as linhas de
   separação existentes nos níveis selecionados.
5. As curvas de contorno são transformadas para coordenadas do hospedeiro,
   achatadas no plano do nível, filtradas (curvas curtas, duplicatas da
   mesma execução, duplicatas de linhas já existentes no modelo) e criadas
   como linhas de separação de espaço numa vista de planta desse nível.

Tudo roda numa única transação: em caso de erro ou cancelamento, nada muda.
Os avisos do Revit gerados ao criar as linhas (ex.: linhas sobrepostas a
paredes) são descartados automaticamente, e a execução dispensa cliques.
"""

__title__ = "Rooms to\nSpace Lines"
__doc__ = (
    u"Lê os ambientes (Rooms) de um modelo de arquitetura vinculado e recria "
    u"os contornos como linhas de separação de espaço no modelo atual, e os "
    u"espaços guardam a referência dos ambientes mesmo se o link mudar. Pode "
    u"ser executado de novo: as linhas existentes nunca são duplicadas."
)
__author__ = "Paulo Giavoni"

import traceback

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    CurveArray,
    ElementId,
    FailureProcessingResult,
    FailureSeverity,
    FilteredElementCollector,
    IFailuresPreprocessor,
    Level,
    Plane,
    RevitLinkInstance,
    SketchPlane,
    SpatialElementBoundaryLocation,
    SpatialElementBoundaryOptions,
    Transaction,
    Transform,
    ViewPlan,
    ViewType,
    XYZ,
)
from System.Collections.Generic import List as NetList

from pyrevit import forms, revit, script

doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

TITLE = "Rooms to Space Lines"

# Tolerâncias geométricas (pés).
DEDUPE_XY = 0.01          # grade de ~3 mm para achar curvas coincidentes
DEDUPE_Z = 0.1            # grade vertical de ~30 mm para o mesmo teste
MAX_LEVEL_DIST = 3.0      # nível do link mais longe que isso de todos os
                          # níveis do hospedeiro -> seus ambientes são pulados
REPLACE_Z_BAND = 1.0      # linhas existentes a esta distância de um nível
                          # selecionado são apagadas no modo Substituir
FT_TO_M = 0.3048


class _UserCancelled(Exception):
    pass


class _SwallowWarnings(IFailuresPreprocessor):
    """Apaga todos os avisos da transação, e a execução dispensa cliques."""

    def PreprocessFailures(self, failures_accessor):
        for msg in failures_accessor.GetFailureMessages():
            try:
                if msg.GetSeverity() == FailureSeverity.Warning:
                    failures_accessor.DeleteWarning(msg)
            except Exception:
                pass
        return FailureProcessingResult.Continue


# ============================================================
# AUXILIARES
# ============================================================
def _loaded_links():
    """título -> RevitLinkInstance de cada link carregado no hospedeiro."""
    out = {}
    for lnk in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        link_doc = lnk.GetLinkDocument()
        if link_doc is None:
            continue
        out[link_doc.Title] = lnk
    return out


def _placed_rooms(link_doc):
    """Todos os ambientes posicionados (Area > 0) do documento vinculado."""
    rooms = []
    for r in (FilteredElementCollector(link_doc)
              .OfCategory(BuiltInCategory.OST_Rooms)
              .WhereElementIsNotElementType()):
        try:
            if r.Area > 0:
                rooms.append(r)
        except Exception:
            pass
    return rooms


def _host_levels():
    levels = list(FilteredElementCollector(doc).OfClass(Level))
    levels.sort(key=lambda lv: lv.ProjectElevation)
    return levels


def _closest_host_level(host_z, host_levels):
    """(Level, distância abs.) do nível hospedeiro mais perto de ``host_z``."""
    best, best_d = None, None
    for lv in host_levels:
        d = abs(lv.ProjectElevation - host_z)
        if best_d is None or d < best_d:
            best, best_d = lv, d
    return best, best_d


def _plan_view_for_level(level_id):
    """Vista para as linhas: de preferência uma planta de piso do nível."""
    fallback = None
    for v in FilteredElementCollector(doc).OfClass(ViewPlan):
        if v.IsTemplate:
            continue
        gl = v.GenLevel
        if gl is None or gl.Id != level_id:
            continue
        if v.ViewType == ViewType.FloorPlan:
            return v
        if fallback is None:
            fallback = v
    return fallback


def _quant_pt(pt, z):
    return (int(round(pt.X / DEDUPE_XY)),
            int(round(pt.Y / DEDUPE_XY)),
            int(round(z / DEDUPE_Z)))


def _curve_key(curve):
    """Impressão digital geométrica de uma curva limitada (independe da ordem).

    Extremidades mais o ponto médio, quantizados numa grade pequena: basta
    para distinguir segmentos retos de curvos e para pegar o mesmo contorno
    trazido duas vezes por dois ambientes vizinhos.
    """
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    pm = curve.Evaluate(0.5, True)
    z = p0.Z
    k0, k1 = _quant_pt(p0, z), _quant_pt(p1, z)
    if k1 < k0:
        k0, k1 = k1, k0
    return (k0, k1, _quant_pt(pm, z))


def _existing_separation_lines():
    """[(elemento, chave ou None, z ou None)] de cada linha de separação."""
    found = []
    for ce in (FilteredElementCollector(doc)
               .OfCategory(BuiltInCategory.OST_MEPSpaceSeparationLines)
               .WhereElementIsNotElementType()):
        key, z = None, None
        try:
            crv = ce.GeometryCurve
            if crv is not None and crv.IsBound:
                key = _curve_key(crv)
                z = crv.GetEndPoint(0).Z
            elif crv is not None:
                z = crv.Evaluate(0.0, True).Z
        except Exception:
            pass
        found.append((ce, key, z))
    return found


def _flatten_to(curve, target_z):
    """Devolve a curva transladada na vertical até ``target_z``."""
    dz = target_z - curve.GetEndPoint(0).Z
    if abs(dz) < 1e-9:
        return curve
    return curve.CreateTransformed(
        Transform.CreateTranslation(XYZ(0.0, 0.0, dz)))


# ============================================================
# 1. ESCOLHA DO MODELO DE ORIGEM (VINCULADO)
# ============================================================
links = _loaded_links()
if not links:
    forms.alert("Nenhum link Revit carregado no projeto.",
                title=TITLE, exitscript=True)

if len(links) == 1:
    chosen = list(links.keys())[0]
else:
    chosen = forms.SelectFromList.show(
        sorted(links.keys()),
        title="Selecione o modelo de origem (ambientes)",
        button_name="Ler ambientes",
        multiselect=False,
    )
if not chosen:
    script.exit()

link_instance = links[chosen]
link_doc = link_instance.GetLinkDocument()
link_transform = link_instance.GetTotalTransform()


# ============================================================
# 2. COLETA DOS AMBIENTES E MAPA NÍVEIS DO LINK -> NÍVEIS DO HOSPEDEIRO
# ============================================================
rooms = _placed_rooms(link_doc)
if not rooms:
    forms.alert(u"O link selecionado não tem ambientes posicionados.",
                title=TITLE, exitscript=True)

host_levels = _host_levels()
if not host_levels:
    forms.alert(u"O modelo atual não tem níveis.",
                title=TITLE, exitscript=True)

# Level.Id do link -> (Level do hospedeiro ou None, delta em pés, nome no link)
level_map = {}
# Level.Id do hospedeiro -> {"level": Level, "rooms": [...]}
rooms_by_host = {}
skipped_no_level = 0
unmatched_levels = {}

for room in rooms:
    try:
        link_level = room.Level
    except Exception:
        link_level = None
    if link_level is None:
        skipped_no_level += 1
        continue

    lid = link_level.Id
    if lid not in level_map:
        host_z = link_transform.OfPoint(
            XYZ(0.0, 0.0, link_level.ProjectElevation)).Z
        host_level, dist = _closest_host_level(host_z, host_levels)
        if host_level is None or dist > MAX_LEVEL_DIST:
            level_map[lid] = (None, dist, link_level.Name)
        else:
            level_map[lid] = (host_level, dist, link_level.Name)

    host_level, dist, link_name = level_map[lid]
    if host_level is None:
        unmatched_levels[link_name] = unmatched_levels.get(link_name, 0) + 1
        continue

    slot = rooms_by_host.setdefault(
        host_level.Id, {"level": host_level, "rooms": []})
    slot["rooms"].append(room)

if not rooms_by_host:
    forms.alert(
        u"Nenhum nível do link pôde ser associado a um nível do modelo atual "
        u"(o mais próximo está a mais de {:.1f} m). Confira as coordenadas "
        u"compartilhadas / os níveis dos dois modelos.".format(
            MAX_LEVEL_DIST * FT_TO_M),
        title=TITLE, exitscript=True)


# ============================================================
# 3. O USUÁRIO ESCOLHE OS NÍVEIS E O MODO
# ============================================================
slots = sorted(rooms_by_host.values(),
               key=lambda s: s["level"].ProjectElevation)
label_to_id = {}
labels = []
for slot in slots:
    lv = slot["level"]
    label = "{}   |   elev. {:.2f} m   |   {} ambiente(s)".format(
        lv.Name, lv.ProjectElevation * FT_TO_M, len(slot["rooms"]))
    labels.append(label)
    label_to_id[label] = lv.Id

picked = forms.SelectFromList.show(
    labels,
    title=u"Selecione os níveis do modelo atual a processar",
    button_name="Continuar",
    multiselect=True,
)
if not picked:
    script.exit()

selected_ids = set(label_to_id[p] for p in picked)
selected_slots = [s for s in slots
                  if s["level"].Id in selected_ids]
total_rooms = sum(len(s["rooms"]) for s in selected_slots)

mode = forms.alert(
    u"Link de origem:  {}\n"
    u"Níveis a processar:  {}\n"
    u"Ambientes a traçar:  {}\n\n"
    u"O que fazer com as linhas de separação de espaço existentes?\n\n"
    u"  -  Só acrescentar as que faltam: mantém tudo o que já está desenhado "
    u"e só cria as linhas que ainda não existem (pode rodar de novo).\n"
    u"  -  Substituir nos níveis selecionados: apaga as linhas de separação "
    u"de espaço dos níveis selecionados e depois recria todas elas a partir "
    u"dos ambientes.".format(chosen, len(selected_slots), total_rooms),
    title=TITLE,
    options=[u"Só acrescentar as que faltam", u"Substituir nos níveis selecionados", "Cancelar"],
)
if not mode or mode == "Cancelar":
    script.exit()
replace_mode = (mode == u"Substituir nos níveis selecionados")

# As vistas de planta são conferidas logo, para o usuário saber das falhas
# antes que qualquer coisa seja modificada.
views_by_level = {}
levels_without_view = []
for slot in selected_slots:
    lv = slot["level"]
    view = _plan_view_for_level(lv.Id)
    if view is None:
        levels_without_view.append(lv.Name)
    else:
        views_by_level[lv.Id] = view

if levels_without_view and not forms.alert(
        u"Não existe vista de planta para estes níveis: as linhas deles não "
        u"podem ser criadas e eles serão pulados:\n\n  {}\n\n"
        u"Continuar com os demais níveis?".format(
            "\n  ".join(levels_without_view)),
        title=TITLE, ok=False, yes=True, no=True):
    script.exit()


# ============================================================
# 4. CRIAÇÃO DAS LINHAS (transação única, reverte em qualquer problema)
# ============================================================
boundary_opts = SpatialElementBoundaryOptions()
boundary_opts.SpatialElementBoundaryLocation = \
    SpatialElementBoundaryLocation.Finish

existing = _existing_separation_lines()
seen_keys = set(k for (_e, k, _z) in existing if k is not None)

short_tol = doc.Application.ShortCurveTolerance

deleted = 0
created = 0
dup_skipped = 0
short_skipped = 0
failed_curves = 0
rooms_no_boundary = 0
per_level_stats = []   # (nome do nível, ambientes, criadas, duplicatas)

t = Transaction(doc, TITLE)
fail_opts = t.GetFailureHandlingOptions()
fail_opts.SetFailuresPreprocessor(_SwallowWarnings())
t.SetFailureHandlingOptions(fail_opts)
t.Start()
try:
    # 4a. Modo Substituir: remove as linhas existentes nos níveis selecionados
    # (e esquece as impressões digitais delas, para poder recriá-las).
    if replace_mode:
        target_zs = [s["level"].ProjectElevation for s in selected_slots
                     if s["level"].Id in views_by_level]
        to_delete = NetList[ElementId]()
        for (elem, key, z) in existing:
            if z is None:
                continue
            if any(abs(z - tz) <= REPLACE_Z_BAND for tz in target_zs):
                to_delete.Add(elem.Id)
                if key is not None:
                    seen_keys.discard(key)
        if to_delete.Count > 0:
            deleted = to_delete.Count
            doc.Delete(to_delete)
            doc.Regenerate()

    # 4b. Traça o contorno de cada ambiente no seu nível do hospedeiro.
    done = 0
    with forms.ProgressBar(title=u"Traçando ambiente {value} de {max_value}",
                           cancellable=True) as pb:
        for slot in selected_slots:
            lv = slot["level"]
            view = views_by_level.get(lv.Id)
            if view is None:
                done += len(slot["rooms"])
                pb.update_progress(done, total_rooms)
                continue

            sketch_plane = SketchPlane.Create(
                doc,
                Plane.CreateByNormalAndOrigin(
                    XYZ.BasisZ, XYZ(0.0, 0.0, lv.ProjectElevation)))

            lv_created = 0
            lv_dups = 0
            for room in slot["rooms"]:
                if pb.cancelled:
                    raise _UserCancelled()

                loops = room.GetBoundarySegments(boundary_opts)
                if loops is None or loops.Count == 0:
                    rooms_no_boundary += 1
                    done += 1
                    pb.update_progress(done, total_rooms)
                    continue

                for loop in loops:
                    for seg in loop:
                        try:
                            crv = seg.GetCurve()
                            if crv is None:
                                continue
                            crv = crv.CreateTransformed(link_transform)
                            crv = _flatten_to(crv, lv.ProjectElevation)
                            if crv.Length < short_tol * 1.01:
                                short_skipped += 1
                                continue
                            key = _curve_key(crv)
                            if key in seen_keys:
                                lv_dups += 1
                                continue
                            arr = CurveArray()
                            arr.Append(crv)
                            doc.Create.NewSpaceBoundaryLines(
                                sketch_plane, arr, view)
                            seen_keys.add(key)
                            lv_created += 1
                        except _UserCancelled:
                            raise
                        except Exception:
                            failed_curves += 1

                done += 1
                pb.update_progress(done, total_rooms)

            created += lv_created
            dup_skipped += lv_dups
            per_level_stats.append(
                (lv.Name, len(slot["rooms"]), lv_created, lv_dups))

    t.Commit()

except _UserCancelled:
    t.RollBack()
    forms.alert(u"Cancelado pelo usuário. Nada foi alterado.",
                title=TITLE, exitscript=True)
except Exception:
    t.RollBack()
    output.print_md(u"## {} - erro (transação revertida)".format(TITLE))
    output.print_md("```\n{}\n```".format(traceback.format_exc()))
    forms.alert(
        u"Ocorreu um erro e a transação foi revertida - o modelo NÃO foi "
        u"modificado. Veja os detalhes na janela de saída.",
        title=TITLE, exitscript=True)


# ============================================================
# 5. RELATÓRIO
# ============================================================
output.print_md("## {}".format(TITLE))
output.print_md("**Link de origem:** {}".format(chosen))
output.print_md(
    "**Modo:** {}".format(u"Substituir nos níveis selecionados"
                          if replace_mode else u"Só acrescentar as que faltam"))

if per_level_stats:
    output.print_table(
        table_data=[[name, rc, cr, dp]
                    for (name, rc, cr, dp) in per_level_stats],
        columns=[u"Nível", "Ambientes", "Linhas criadas", "Duplicatas puladas"],
        title=u"Níveis processados",
    )

output.print_md(u"- Linhas de separação criadas: **{}**".format(created))
if deleted:
    output.print_md("- Linhas existentes apagadas (modo Substituir): **{}**"
                    .format(deleted))
if dup_skipped:
    output.print_md(u"- Curvas puladas (já existentes): **{}**"
                    .format(dup_skipped))
if short_skipped:
    output.print_md(u"- Curvas puladas (abaixo do comprimento mínimo): **{}**"
                    .format(short_skipped))
if failed_curves:
    output.print_md("- Curvas que o Revit se recusou a criar: **{}**"
                    .format(failed_curves))
if rooms_no_boundary:
    output.print_md("- Ambientes sem contorno (pulados): **{}**"
                    .format(rooms_no_boundary))
if skipped_no_level:
    output.print_md(u"- Ambientes sem nível (pulados): **{}**"
                    .format(skipped_no_level))
if unmatched_levels:
    output.print_md(
        u"- Ambientes em níveis do link **sem par no modelo atual**: {}"
        .format(", ".join("{} ({} ambiente(s))".format(n, c)
                          for n, c in sorted(unmatched_levels.items()))))
if levels_without_view:
    output.print_md(
        u"- Níveis pulados por falta de vista de planta: {}"
        .format(", ".join(levels_without_view)))

forms.alert(
    u"{} linha(s) de separação de espaço criada(s) a partir de \"{}\".{}".format(
        created, chosen,
        u"\n{} linha(s) existente(s) substituída(s).".format(deleted)
        if deleted else ""),
    title=TITLE,
)
