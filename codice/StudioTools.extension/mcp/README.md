# Claude Chat per Revit (pyRevit + Claude Code CLI + MCP)

Un pannello di chat dentro pyRevit che parla con il **Claude Code CLI**, il
quale può **leggere e modificare il modello Revit aperto**.

## Come funziona

```
Pannello "Claude Chat" (WPF, dentro Revit)
   └─subprocess─▶ claude -p  (Claude Code CLI, il tuo abbonamento)
                     └─MCP (stdio)─▶ revit_mcp_server.py  (questo file)
                                        └─HTTP 127.0.0.1:48884─▶ pyRevit Routes
                                                                    └─▶ API di Revit (modello vivo)
```

- `../../startup.py` — registra l'API Routes `revit-mcp` dentro Revit
  (endpoint `/revit-mcp/status`, `/model-info`, `/execute`). Gli handler girano
  sul **thread principale** di Revit (ExternalEvent), quindi si possono aprire
  `Transaction`.
- `revit_mcp_server.py` — server MCP minimale (solo stdlib Python 3) che espone
  a Claude gli strumenti `revit_execute`, `revit_status`, `revit_model_info` e
  inoltra le chiamate al Routes via HTTP.
- `../Studio.tab/AI.panel/ClaudeChat.pushbutton/` — il pannello di chat.

Tutto è su **localhost**: nessuna esposizione in rete.

## Setup (una tantum)

1. **Login del CLI** — esegui `Login_Claude.bat` (o in un terminale:
   `%USERPROFILE%\.local\bin\claude.exe setup-token`). Approva nel browser.
2. **Routes attivo su loopback** — in `pyRevit_config.ini`, sezione `[routes]`,
   devono esserci (gia impostati):
   ```
   enabled = true
   host = "127.0.0.1"
   ```
   `host = "127.0.0.1"` fa ascoltare il server SOLO in loopback: Windows non
   filtra il loopback, quindi **niente prompt del firewall e nessun bisogno di
   permessi da amministratore**. Senza `host`, pyRevit ascolta su tutte le
   interfacce (0.0.0.0) e Windows chiede l'autorizzazione (admin).
3. **Ricarica pyRevit** — pyRevit → Reload (o riavvia Revit), cosi lo
   `startup.py` registra il bridge e il server Routes parte sulla 48884.
4. Apri **Studio → AI → Claude Chat** e scrivi una richiesta.

## Verifica rapida

Con Revit aperto e Routes attivo:

```
curl http://127.0.0.1:48884/revit-mcp/status
```

Deve rispondere `{"status":"active", ... "document":"<titolo>"}`.

## Sicurezza

`revit_execute` esegue codice (IronPython 2.7) nel contesto di Revit: molto
potente. È uno strumento locale personale, solo su 127.0.0.1. Il pannello
autorizza a Claude **solo** gli strumenti `mcp__revit__*` più i tool di sola
lettura (Read/Grep/Glob): non può modificare file né eseguire shell.
