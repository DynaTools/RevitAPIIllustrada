# Códigos — Revit API Ilustrada em Python

Todo o código do livro *Revit API Ilustrada em Python* (edição brasileira),
**um arquivo por bloco**, pronto para copiar e colar no **RevitPythonShell**.
A indentação está exata (copiar do PDF a perde).

Autor: **Paulo Giavoni** · DynaTools

## Como funciona

No livro, embaixo de cada bloco de código, o selo vermelho
**</> Código P.C.n · copiar** leva ao arquivo correspondente aqui. O nome do
arquivo é `codice-P-C-n.py`:

- **P** = parte, **C** = capítulo, **n** = número do código no capítulo.
- Exemplo: *Código 6.1.2* → `codice-6-1-2.py`.

O *Índice dos códigos*, no fim do livro, lista todos os códigos com a página.

Os comentários e as mensagens estão em português. Os nomes de variáveis
ficaram como no original. Os nomes que o código procura ou grava no modelo
estão em português: os parâmetros nativos com o nome do Revit em português
(`Comentários`, que no Revit em inglês se chama `Comments`) e os que os
tutoriais criam com nome traduzido (`COD_AMBIENTE`, `Qtd suportes`,
`Espaçamento suportes`, `WBS_CODIGO`, o workset `FURAÇÃO`...). Os nomes do
modelo de exemplo da Autodesk (níveis, tipos, famílias) ficam em inglês.
Se o seu modelo usa outros nomes, troque-os na linha indicada.

> **CPython 3.** Os blocos com `openpyxl` rodam só no engine CPython 3 do
> pyRevit (primeira linha `#! python3` e biblioteca instalada).

> **Seleção → NÃO MODAL.** Os scripts com `PickObject` / `PickObjects`
> devem ser executados com o RevitPythonShell no modo **não modal**; senão o
> clique não chega ao modelo.

Os grafos Dynamo (`.dyn`) seguem as mesmas regras: nomes de nós e de
grupos, comentários e textos em português; variáveis e nomes da API como
no original. As extensões pyRevit
(`.zip`) também estão em português: descompacte a pasta `.extension`,
registre-a no pyRevit Settings e clique em Reload.

| Arquivo | O que é | Capítulo |
|---|---|---|
| `RevitApiBook.extension.zip` | a guia do livro: Furação, Comprimento, Ocupação e Suportes | 7.1, 8.1–8.3 |
| `Comprimento.extension.zip` | o botão Comprimento sozinho, como nasce no capítulo | 8.1 |
| `Suportes.extension.zip` | o botão Suportes sozinho, como nasce no capítulo | 8.3 |
| `StudioTools.extension.zip` | a barra de ferramentas completa do autor e a ponte MCP | 7.4, 7.5 |
| `janela-exemplo.xaml` | a janela do exemplo do pyRevit | 5.1 |
| `codice-7-3-tabella.xlsx` | a tabela da WBS | 7.3 |
| `Probe_LUX.rfa`, `Probe_WIFI.rfa` | as famílias-sonda da luminotécnica e do Wi-Fi | 8.5, 8.6 |

© 2026 Paulo Giavoni. Autodesk e Revit são marcas registradas da
Autodesk, Inc.; este projeto é independente e não é afiliado à Autodesk.
