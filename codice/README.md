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

Os comentários e as mensagens estão em português. Os nomes de variáveis e
os nomes que o código procura no modelo (parâmetros, tipos, níveis,
worksets) ficaram como no modelo de exemplo do livro: se o seu modelo usa
outros nomes, troque-os na linha indicada.

> **CPython 3.** Os blocos com `openpyxl` rodam só no engine CPython 3 do
> pyRevit (primeira linha `#! python3` e biblioteca instalada).

> **Seleção → NÃO MODAL.** Os scripts com `PickObject` / `PickObjects`
> devem ser executados com o RevitPythonShell no modo **não modal**; senão o
> clique não chega ao modelo.

Os arquivos que não são `.py` (grafos Dynamo `.dyn`, extensões pyRevit
`.zip`, famílias `.rfa`, planilha `.xlsx`) são os mesmos da edição
italiana.

© 2026 Paulo Giavoni. Autodesk e Revit são marcas registradas da
Autodesk, Inc.; este projeto é independente e não é afiliado à Autodesk.
