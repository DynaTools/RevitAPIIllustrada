# Edição brasileira — tabela única de nomes

Esta tabela vale para **tudo** o que o leitor instala, baixa ou vê: os
scripts do RevitPythonShell (`codice/`), as extensões pyRevit
(`extensoes/`), os grafos Dynamo (`.dyn`), os consoles das janelas RPS e o
texto do livro. Se um nome muda aqui, muda em todos esses lugares juntos.

Princípio: **o que o próprio livro cria ou mostra** (botões, painéis,
worksets, parâmetros criados nos tutoriais, nomes de transação, mensagens)
fica em português. **O que vem de fora** (o modelo Snowdon da Autodesk, os
nomes da API, designações comerciais de cabos, famílias `.rfa` que não
editamos) fica como está.

## Faixa de opções (pyRevit)

A interface do pyRevit é a árvore de pastas: o nome da pasta é o rótulo
do botão. As pastas usam só ASCII (zip e Windows sem surpresas); quando o
rótulo leva acento, o `title:` do `bundle.yaml` o escreve com acento.

| Italiano (pasta) | Pasta PT | Rótulo na faixa |
|---|---|---|
| `RevitApiBook.extension` / `RevitApiBook.tab` | (mantém) | RevitApiBook |
| `Coordina.panel` | `Coordenar.panel` | Coordenar |
| `Misura.panel` | `Medir.panel` | Medir |
| `Verifica.panel` | `Verificar.panel` | Verificar |
| `Forometria.pushbutton` | `Furacao.pushbutton` | Furação |
| `Lunghezza.pushbutton` | `Comprimento.pushbutton` | Comprimento |
| `Riempimento.pushbutton` | `Ocupacao.pushbutton` | Ocupação |
| `Staffaggio.pushbutton` | `Suportes.pushbutton` | Suportes |
| `Lunghezza.extension` / `Lunghezza.tab` | `Comprimento.extension` / `Comprimento.tab` | Comprimento |
| `Staffaggio.extension` / `Staffaggio.tab` | `Suportes.extension` / `Suportes.tab` | Suportes |
| `ForometriaWindow.xaml` (classe `ForometriaWindow`) | `FuracaoWindow.xaml` (classe `FuracaoWindow`) | — |
| `StaffaggioWindow.xaml` (classe `StaffaggioWindow`) | `SuportesWindow.xaml` (classe `SuportesWindow`) | — |
| `StudioTools.extension` / `Studio.tab` | (mantém) | Studio |
| `Ensino.panel/RecSessione.smartbutton` | `Ensino.panel/RecSessao.smartbutton` | Rec Sessão |

Os demais botões do StudioTools mantêm os nomes em inglês (Clash
Detective, Place Sleeves, Smart Location…), como no catálogo do cap. 7.4.

Exemplos didáticos do cap. 5.1 e do Apêndice A (não são downloads
prontos, são pastas que o leitor cria):

| Italiano | PT |
|---|---|
| `Azienda.extension` / `Azienda.tab` | `Empresa.extension` / `Empresa.tab` |
| `Coordinamento.panel` | `Coordenacao.panel` (rótulo Coordenação) |
| `Evidenzia Canali.pushbutton` | `Destacar Dutos.pushbutton` |
| `Cancella Modelli di Vista.pushbutton` | `Apagar Templates.pushbutton` |
| `Rinomina Workset.pushbutton` | `Renomear Workset.pushbutton` |
| `MiaSquadra.extension` | `MinhaEquipe.extension` |
| `Strumenti.panel` | `Ferramentas.panel` |
| `FirmaPorte.pushbutton` | `AssinarPortas.pushbutton` |

## Parâmetros, worksets e nomes gravados no modelo

| Italiano | PT | Observação |
|---|---|---|
| `Commenti` (parâmetro nativo) | `Comentários` | nome do Revit em PT-BR; o texto explica que em Revit em inglês é `Comments` |
| `Marca` | `Marca` | igual no Revit PT-BR |
| `COD_LOCALE` | `COD_AMBIENTE` | parâmetro criado no cap. 4 |
| `Stato` / `Da verificare` | `Status` / `A verificar` | |
| `Staffe n` | `Qtd suportes` | parâmetros criados no cap. 8.3 |
| `Staffe interasse` | `Espaçamento suportes` | |
| workset `FOROMETRIA` | workset `FURAÇÃO` | criado pela ferramenta |
| `Clash conduit {} vs {}` | `Clash eletroduto {} vs {}` | DirectShape criado pelo passo 1 |
| `Foro D{} conduit {}` | `Furo D{} eletroduto {}` | DirectShape criado pelo passo 2 |
| prefixos procurados `Clash conduit` / `Foro D` | `Clash eletroduto` / `Furo D` | o passo 3 apaga o que os passos 1 e 2 criaram |
| `Foro passante D{}` | `Furo passante D{}` | Marca/Comentários dos furos definitivos |
| `WBS_CODICE` | `WBS_CODIGO` | `WBS_s01…WBS_t02` mantêm |
| `wbs_condivisi.txt` | `wbs_compartilhados.txt` | |
| `wbs_elementi.csv` | `wbs_elementos.csv` | |
| `Raggio di curvatura` / `Angolo` | `Raio de curvatura` / `Ângulo` | sempre depois de `Bend Radius` / `Angle` na lista de tentativas |
| `Lunghezza circuito` | `Comprimento do circuito` | |
| `Verificato` | `Verificado` | |
| `TEST-REPLICARE` | `TESTE-REPLICAR` | |
| níveis `Piano Terra`, `Piano 1`, `Piano 2` | `Térreo`, `Pavimento 1`, `Pavimento 2` | exemplos do cap. 2–3 |
| `Muro 01` | `Parede 01` | |
| tipos `Muro generico - 200 mm`, `Parete di base - Muratura 150` | `Parede genérica - 200 mm`, `Parede básica - Alvenaria 150` | nos consoles |
| `Probe_LUX`, `Probe_WIFI` | (mantêm) | nomes das famílias `.rfa` |
| prefixo `Lux ` | `Lux ` | |
| `FG16R16 …`, `FG16OR16 …` | (mantêm) | designações comerciais dos cabos |
| nomes do modelo Snowdon (`Level 1`, `L1 - Block 35`…) | (mantêm) | modelo da Autodesk, em inglês |

## Rótulos que o código imprime ou pinta

| Italiano | PT |
|---|---|
| `CONFORME` / `AL LIMITE` / `NON CONFORME` | `CONFORME` / `NO LIMITE` / `NÃO CONFORME` |
| `verde` / `giallo` / `rosso` | `verde` / `amarelo` / `vermelho` |
| `ESITO` | `RESULTADO` |
| `sfrido` | `sobra` |
| botão do Revit `FINE` / `Finish` | `Concluir` |
| `Fora` (botão da janela) | `Furar` |
| `Annulla` | `Cancelar` |

## Normas

As normas citadas (CEI 64-8, CEI EN 61537, UNI EN 12464-1) ficam com o
nome original: o método do livro foi escrito sobre elas. Adaptar os
limites à NBR 5410 é uma decisão de conteúdo do autor, não de tradução.
