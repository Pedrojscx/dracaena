# B1 — bandeja, IPC e atalhos

Implementação em `feat/b1-frontend`, exclusivamente em `tray/`, `hotkeys/` e
`ipc_client/`. O contrato é **provisório**, compatível com o stub A1 de
`~/wt/frontend-provisorio`. Não representa validação do daemon final.

## Integração pelo A1

Dependências validadas: Python 3.14, PySide6 6.12.0; python-xlib no X11.

```python
from dracaena.ui.ipc_client import IpcClient
from dracaena.ui.tray import TrayController

app.setQuitOnLastWindowClosed(False)
client = IpcClient()                      # socket_name=None => ctl.sock / pipe do contrato
client.connected.connect(lambda: state.set_connected(True))
client.disconnected.connect(lambda: state.set_connected(False))
client.event_received.connect(lambda m: state.apply_state_event(m.data) if m.event == 'state' else None)
tray = TrayController(client, host)
tray.bind_state(state)
if not tray.show():                       # lock entre processos; também conecta ao daemon
    raise SystemExit(0)
tray.tray_availability.connect(lambda ok, aviso: ...)   # aviso quando não há bandeja
app.aboutToQuit.connect(tray.close)
```

`show()` chama `client.connect_to_daemon()`. O cliente assina sozinho, a cada conexão,
os eventos `state, log, question, verdict, probe, shortcut_test`.

### IpcClient
Sinais: `connected`, `disconnected`, `event_received(EventMsg)`, `availability_changed(bool, texto)`,
`request_timeout(id)`, `protocol_error(texto)`. `request(cmd, args=None, callback=None, timeout_ms=None)`:
o prazo padrão é 5 s; `probe.start` deve passar `timeout_ms` maior. Callback recebe
`Response(id, ok, data, error=IpcError(code, message))`. Não há reenvio após desconexão.

Contrato IPC v0 coberto: endpoint `ctl.sock` (Linux) / named pipe `dracaena-<usuário>` (Windows);
JSON por linha; resposta sem campo `v`; `data` pode ser lista; erro = `error` (texto) + `code`;
evento plano sem `id`. Evento desconhecido ou versão ≠ 0 derruba a conexão e emite `protocol_error`.

### Bandeja sem bandeja (fallback)
No Linux o controlador observa `org.kde.StatusNotifierWatcher` (QDBusServiceWatcher): quando o
serviço surge, o ícone é recriado e exibido; quando some, o ícone é ocultado. Que o host da bandeja
possa surgir depois do app é uma **hipótese** (não verificada em desktops reais). Sem D-Bus ou fora do
Linux usa-se `QSystemTrayIcon.isSystemTrayAvailable()`. Sem bandeja o app continua funcionando e
`tray_availability(False, aviso)` traz o texto de `docs/ui-fluxos.md` (GNOME/Hyprland conforme
`XDG_CURRENT_DESKTOP`, mais o aviso geral); a mesma mensagem vai ao aviso da UI uma única vez.

### Início automático (decisão do contrato, 4ª rodada)
`set_autostart(enabled, argv)` grava **exatamente** o argv recebido (sem montar caminho próprio):
Linux `~/.config/autostart/dracaena.desktop`; Windows chave Run `DracaenaUI` (NÃO VALIDADO em
Windows nativo). `autostart_command(base)` acrescenta `--background` uma vez ao argv de
`platform.launch_cmd()`. `is_autostart_enabled()` / `autostart_argv()` leem o arquivo/chave e
refletem o estado real (`Hidden=true` e `X-GNOME-Autostart-enabled=false` contam como desligado).
Só ativar por ação explícita em Configurações. Todos aceitam `config_home=` para testes.

### Demais pontos
`TrayController(client, host)`; `bind_state(app_state)`; atalho: `register_hotkey()` (Windows/X11).
No Wayland o atalho é feito pelo compositor chamando `dracaena toggle`. Notificações usam uma
janela Qt reutilizada (4,5 s). Menu: Iniciar, Pausar/Retomar (toggle), Parar (stop), Responder só
esta questão (ask), Abrir configuração, Adicionar site, Diagnóstico (doctor), Sair.
Callbacks do host: `open_settings()`, `open_add_site()`, `open_shortcut_wizard()`, `quit_app()`,
opcional `show_diagnostics(data)`. Sair encerra a UI, sem enviar stop ao daemon.

## Testes
```sh
cd ~/wt/b1-frontend && PYTHONPATH=lib QT_QPA_PLATFORM=offscreen \
  python -m unittest discover -s lib/dracaena/ui -p 'test_*.py' -t lib
```
Integração com o daemon real (`ipc_client/test_daemon_integration.py`): defina
`DRACAENA_BACKEND_ROOT` (raiz do backend) e, se preciso, `DRACAENA_DAEMON_PYTHON` (python com as
dependências do daemon). Sem isso, ou se o daemon não subir, o teste é PULADO com o motivo.
`tray/test_watcher.py` usa um dbus-daemon de sessão privado (pulado sem dbus-daemon).

Não validado: Windows nativo; GNOME/KDE/Hyprland reais; X11 só no Xvfb.
