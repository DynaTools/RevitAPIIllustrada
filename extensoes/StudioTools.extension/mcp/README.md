# Ponte MCP para o Revit (pyRevit + Claude Code CLI + MCP)

A ponte que deixa o **Claude Code CLI** (num painel de chat ou no terminal)
**ler e modificar o modelo Revit aberto**.

## Como funciona

```
Painel "Claude Chat" (WPF, dentro do Revit)
   └─subprocess─▶ claude -p  (Claude Code CLI, a sua assinatura)
                     └─MCP (stdio)─▶ revit_mcp_server.py  (este arquivo)
                                        └─HTTP 127.0.0.1:48884─▶ pyRevit Routes
                                                                    └─▶ API do Revit (modelo vivo)
```

- `../startup.py` — registra a API Routes `revit-mcp` dentro do Revit
  (endpoints `/revit-mcp/status`, `/model-info`, `/execute`). Os handlers rodam
  na **thread principal** do Revit (ExternalEvent), então é possível abrir
  `Transaction`.
- `revit_mcp_server.py` — servidor MCP mínimo (só a stdlib do Python 3) que expõe
  ao Claude os tools `revit_execute`, `revit_status`, `revit_model_info` e
  repassa as chamadas ao Routes via HTTP.
- O painel de chat **não vem no pacote**: é uma janela WPF mínima que o
  Capítulo 7.5 do livro explica como montar no seu próprio painel. Sem ele,
  a mesma cadeia funciona pelo terminal, com o `claude` configurado com este
  servidor MCP.

Tudo fica em **localhost**: nenhuma exposição na rede.

## Configuração (uma vez só)

1. **Login do CLI** — execute `Login_Claude.bat` (ou, em um terminal:
   `%USERPROFILE%\.local\bin\claude.exe setup-token`). Aprove no navegador.
2. **Routes ativo no loopback** — no `pyRevit_config.ini`, seção `[routes]`,
   precisam estar presentes (já configurados):
   ```
   enabled = true
   host = "127.0.0.1"
   ```
   `host = "127.0.0.1"` faz o servidor escutar SÓ no loopback: o Windows não
   filtra o loopback, então **nada de aviso do firewall e nenhuma necessidade de
   permissões de administrador**. Sem `host`, o pyRevit escuta em todas as
   interfaces (0.0.0.0) e o Windows pede a autorização (admin).
3. **Recarregue o pyRevit** — pyRevit → Reload (ou reinicie o Revit), assim o
   `startup.py` registra a ponte e o servidor Routes sobe na porta 48884.
4. Registre o servidor no Claude Code (uma vez só), por exemplo:
   `claude mcp add revit -- python caminho\para\mcp\revit_mcp_server.py`,
   e escreva o pedido no seu painel de chat ou no terminal.

## Verificação rápida

Com o Revit aberto e o Routes ativo:

```
curl http://127.0.0.1:48884/revit-mcp/status
```

Deve responder `{"status":"active", ... "document":"<título>"}`.

## Segurança

`revit_execute` executa código (IronPython 2.7) no contexto do Revit: é muito
poderoso. É uma ferramenta local e pessoal, só em 127.0.0.1. O painel
autoriza o Claude a usar **só** os tools `mcp__revit__*` mais os tools de
somente leitura (Read/Grep/Glob): ele não pode modificar arquivos nem executar
comandos de shell.
