# -*- coding: utf-8 -*-
"""Explicações didáticas para os guias do Rec Sessão (português do Brasil).

As chaves de COMANDI são os nomes das transações do Revit exatamente como
ficam registrados no steps.jsonl (no idioma da interface do Revit, sem os
aceleradores '&'). As chaves de FINESTRE são os ids brutos das janelas (o
campo `dialog_id` do steps.jsonl).

Os comandos desconhecidos aparecem listados no fim de cada README gerado:
acrescente-os aqui e gere o guia de novo; o guia melhora a cada sessão.
"""

COMANDI = {
    u"Reference Plane": {
        "titolo": u"Plano de referência",
        "testo": (
            u"Cria um plano de referência: o esqueleto invisível da "
            u"família. A geometria não se desenha “à mão livre” — ela se "
            u"prende aos planos de referência, que guiam o seu "
            u"comportamento paramétrico."),
    },
    u"Place Dimensions": {
        "titolo": u"Cota",
        "testo": (
            u"Insere uma cota. No editor de famílias as cotas não são "
            u"simples anotações: travadas ou rotuladas com um parâmetro, "
            u"elas se tornam as restrições que comandam a geometria."),
    },
    u"Toggle EQ": {
        "titolo": u"Restrição de igualdade (EQ)",
        "testo": (
            u"Ativa a restrição de igualdade na cota: os segmentos ficam "
            u"sempre iguais entre si e a geometria continua centralizada "
            u"quando as dimensões mudam."),
    },
    u"Toggle Lock": {
        "titolo": u"Travamento da restrição",
        "testo": (
            u"Fecha o cadeado de um alinhamento ou de uma cota: a relação "
            u"se mantém mesmo quando o modelo muda. É o gesto que "
            u"transforma um desenho em um sistema de regras."),
    },
    u"Modify element attributes": {
        "titolo": u"Modificação das propriedades",
        "testo": (
            u"Modifica as propriedades dos elementos selecionados — por "
            u"exemplo, a rotulagem de uma cota com um parâmetro ou uma "
            u"mudança na paleta Propriedades."),
    },
    u"Add Parameter": {
        "titolo": u"Novo parâmetro",
        "testo": (
            u"Cria um parâmetro de família: daqui em diante aquele valor "
            u"deixa de ser um número fixo e vira uma variável, que se pode "
            u"alterar para cada tipo ou instância."),
    },
    u"Solid Extrusion": {
        "titolo": u"Extrusão sólida",
        "testo": (
            u"Inicia uma extrusão sólida: desenha-se um perfil 2D em um "
            u"esboço e o Revit o extruda perpendicularmente ao plano de "
            u"trabalho."),
    },
    u"Create Sketch": {
        "titolo": u"Criação do esboço",
        "testo": (
            u"Abre o modo de esboço: um ambiente de desenho 2D protegido, "
            u"onde se define o perfil da geometria."),
    },
    u"Line - Rectangle": {
        "titolo": u"Retângulo",
        "testo": (
            u"Desenha um retângulo de linhas no esboço ativo. Repare nas "
            u"cotas automáticas de esboço que o Revit acrescenta sozinho."),
    },
    u"Finish sketch": {
        "titolo": u"Concluir esboço",
        "testo": (
            u"Conclui o esboço: o Revit valida o perfil (fechado, sem "
            u"interseções) e gera a geometria sólida."),
    },
    u"Family type": {
        "titolo": u"Tipo de família",
        "testo": (
            u"Operação sobre os tipos de família: criação ou troca do tipo "
            u"corrente."),
    },
    u"Family Types": {
        "titolo": u"Aplicação dos tipos de família",
        "testo": (
            u"Aplica os valores definidos na janela Tipos de família: é o "
            u"“flex test” — mudam-se os parâmetros e verifica-se se a "
            u"geometria acompanha sem quebrar."),
    },
    u"Wall - Line": {
        "titolo": u"Parede (traçado linear)",
        "testo": u"Cria uma parede desenhando o seu traçado com uma linha.",
    },
    u"Room": {
        "titolo": u"Ambiente",
        "testo": (
            u"Insere um ambiente (room): o Revit calcula a área e o "
            u"perímetro a partir dos elementos que o delimitam."),
    },
    u"Delete Selection": {
        "titolo": u"Exclusão",
        "testo": u"Exclui os elementos selecionados.",
    },
    u"Copy": {
        "titolo": u"Cópia",
        "testo": u"Copia os elementos selecionados para uma nova posição.",
    },
    u"Drag": {
        "titolo": u"Arraste",
        "testo": (
            u"Modificação direta, arrastando com o mouse o elemento ou as "
            u"suas alças."),
    },
    u"Drag refplane model end": {
        "titolo": u"Arraste do plano de referência",
        "testo": (
            u"Alonga ou desloca a extremidade de um plano de referência, "
            u"arrastando-a."),
    },
}

FINESTRE = {
    "Dialog_Revit_ParamPropertiesFamily": {
        "titolo": u"Janela: Propriedades do parâmetro",
        "testo": (
            u"A janela de criação/modificação de um parâmetro: nome, "
            u"disciplina, tipo de dado, agrupamento e a escolha crucial "
            u"entre parâmetro de tipo e de instância."),
    },
    "Dialog_Family_FamilyType": {
        "titolo": u"Janela: Tipos de família",
        "testo": (
            u"A sala de controle da família: para cada tipo se definem "
            u"valores, fórmulas e travamentos dos parâmetros."),
    },
    "Dialog_Revit_Name": {
        "titolo": u"Janela: Nome",
        "testo": u"Atribuição do nome (por exemplo, a um novo tipo).",
    },
    "TaskDialog": {
        "titolo": u"Aviso do Revit",
        "testo": u"",
    },
}
