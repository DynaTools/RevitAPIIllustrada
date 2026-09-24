# -*- coding: utf-8 -*-
"""Atualiza / regenera os gráficos da vista ativa.

Corrige o defeito comum em que uma vista 3D (ou outra) não mostra nada, mas os
elementos continuam lá (ainda dá para selecioná-los com clique ou com janela).
É uma dessincronização do cache gráfico / de exibição, NÃO geometria perdida.

A ferramenta aplica, na vista ATIVA, cada “empurrão” da API que obriga o Revit
a reconstruir a exibição:

  * limpa Ocultar/isolar temporariamente, Revelar elementos ocultos ou
    propriedades temporárias que tenham ficado travados
  * alterna o Nível de detalhe e o Estilo visual e depois os devolve
  * regenera o documento
  * atualiza a vista ativa e a reativa (troca de vista e volta)
  * coleta a memória gerenciada (GC do .NET)

Nada é excluído e as configurações da vista são restauradas. Pode ser desfeito
com Ctrl+Z.
"""
from pyrevit import revit, DB, forms, script
import System

__title__ = "Refresh\nGraphics"
__author__ = "Paulo Giavoni"

uidoc = revit.uidoc
doc = revit.doc
output = script.get_output()

view = doc.ActiveView if doc else None
if view is None:
    forms.alert("Nenhuma vista ativa.", title="Atualizar gráficos", warn_icon=True)
    script.exit()

done = []

# --------------------------------------------------------------------------
# 1. transação: limpa modos temporários travados + alterna gráficos + regenera
# --------------------------------------------------------------------------
TEMP_MODES = [
    ("Ocultar/isolar temporariamente", DB.TemporaryViewMode.TemporaryHideIsolate),
    ("Revelar elementos ocultos", DB.TemporaryViewMode.RevealHiddenElements),
    ("Propriedades temporárias da vista", DB.TemporaryViewMode.TemporaryViewProperties),
]

t = DB.Transaction(doc, "Atualizar gráficos da vista")
t.Start()
try:
    for label, mode in TEMP_MODES:
        try:
            if view.IsInTemporaryViewMode(mode):
                view.DisableTemporaryViewMode(mode)
                done.append("Limpo: " + label)
        except Exception:
            pass

    # alterna o Nível de detalhe e volta (força a reconstrução da exibição)
    try:
        original = view.DetailLevel
        alt = (DB.ViewDetailLevel.Fine
               if original != DB.ViewDetailLevel.Fine
               else DB.ViewDetailLevel.Coarse)
        view.DetailLevel = alt
        doc.Regenerate()
        view.DetailLevel = original
        done.append("Nível de detalhe alternado")
    except Exception:
        pass

    # alterna o Estilo visual e volta
    try:
        original_ds = view.DisplayStyle
        alt_ds = (DB.DisplayStyle.Wireframe
                  if original_ds != DB.DisplayStyle.Wireframe
                  else DB.DisplayStyle.Shading)
        view.DisplayStyle = alt_ds
        doc.Regenerate()
        view.DisplayStyle = original_ds
        done.append("Estilo visual alternado")
    except Exception:
        pass

    doc.Regenerate()
    t.Commit()
    done.append("Documento regenerado")
except Exception as ex:
    if t.HasStarted() and not t.HasEnded():
        t.RollBack()
    output.print_md("A etapa da transação falhou: `{}`".format(ex))

# --------------------------------------------------------------------------
# 2. fora da transação: atualiza e reativa a vista ativa
# --------------------------------------------------------------------------
try:
    uidoc.RefreshActiveView()
    done.append("Vista ativa atualizada")
except Exception:
    pass

try:
    other_id = None
    for uv in uidoc.GetOpenUIViews():
        if uv.ViewId != view.Id:
            other_id = uv.ViewId
            break
    if other_id is not None:
        other_view = doc.GetElement(other_id)
        uidoc.ActiveView = other_view
        uidoc.ActiveView = view
        uidoc.RefreshActiveView()
        done.append("Vista reativada (redesenho completo)")
    else:
        done.append("Só uma vista aberta - não foi possível trocar e voltar")
except Exception:
    pass

# --------------------------------------------------------------------------
# 3. libera a memória gerenciada
# --------------------------------------------------------------------------
try:
    System.GC.Collect()
    System.GC.WaitForPendingFinalizers()
    done.append("Memória gerenciada coletada")
except Exception:
    pass

# --------------------------------------------------------------------------
# relatório
# --------------------------------------------------------------------------
output.print_md("### Atualizar gráficos - {}".format(view.Name))
for d in done:
    output.print_md("- " + d)

forms.alert(
    "Atualização dos gráficos concluída na vista:\n{}\n\n"
    "Se ela AINDA estiver em branco, tente nesta ordem:\n"
    "  1. Zoom para ajustar (digite ZF)\n"
    "  2. mude o Estilo visual à mão (Estrutura de arame e depois de volta)\n"
    "  3. alterne Linhas finas (digite TL)\n"
    "  4. verifique se há uma Caixa de corte colapsada\n"
    "  5. feche o modelo e marque Auditar ao reabri-lo.".format(view.Name),
    title="Atualizar gráficos", warn_icon=False)
