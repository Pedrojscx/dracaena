# UI do DRACAENA: arquitetura, fluxos e textos (alinhado ao CONTRATO v0, nota contrato-do-dracaena, 2026-11-10)

## Regras
- A UI só fala com o daemon pelo IPC v0 (`ui/ipc/client.py`). Nunca com a página nem com o navegador. Nunca clica na página.
- Toolkit: PySide6 (padrão, salvo decisão do humano). Escopo: só atividades de prática; nenhum nome de empresa ou curso nos textos.
- O protocolo vive só em `ui/ipc_client/` (B1). Daemon de teste: `PYTHONPATH=lib python3 -m dracaena.cli daemon --simulate` (worktree b2-backend), socket `$XDG_RUNTIME_DIR/dracaena/ctl.sock`.

## Camadas e donos
| Caminho (lib/dracaena/ui/) | Papel | Dono |
|---|---|---|
| `ipc_client/` (codec, cliente QLocalSocket, testes) | transporte e mensagens (único ponto que muda com o CONTRATO). O esqueleto `ipc/` do A1 é só referência: vale o do B1 | B1 |
| `state.py` | `AppState`: estado do daemon, config e conexão, em sinais Qt; as telas só leem daqui | A1 |
| `host.py` | `UiHost`: callbacks bandeja → telas | A1 |
| `tray/` (inclui lifecycle: lock e autostart), `hotkeys/` | bandeja, ícone, menu, atalho Windows/X11 | B1 |
| `settings/`, `shortcuts_wizard/`, `add_site/`, `firstrun/` | janelas | B2 |
| `app.py` | monta QApplication, AppState, IpcClient, bandeja e telas | A1 |

Fluxo de dados: daemon → `IpcClient.event_received` → `AppState` → sinais → bandeja e telas. Ação do usuário → tela/bandeja → `AppState`/`IpcClient.request`. Telas e bandeja não se importam entre si; só `UiHost`.

## Estados da bandeja (ícone e dica)
Estados do evento `state` do CONTRATO: `idle`=parado, `running`=rodando, `paused`=pausado, `error`=erro (mais "sem conexão", só da UI); menu **Iniciar, Pausar/Retomar, Parar**, ask, doctor, Configurações, Sair. Itens habilitados por estado: idle→Iniciar; running→Pausar, Parar; paused→Retomar, Parar; error→Iniciar, Diagnóstico. Iniciar/Pausar/Retomar usam `toggle`; Parar usa `stop`; "Responder só esta questão" usa `ask`. Sem sites (`sites.list` vazio) a UI abre a primeira execução.

## Fluxo 1: primeira execução (B2)
1. Sem sites → abre `first_run`: "Bem-vindo ao DRACAENA. Ele ajuda em atividades de prática. Vamos configurar em dois passos."
2. Passo 1, Adicionar site (fluxo 3). Passo 2, Atalho (fluxo 2). Passo opcional: "Iniciar com o sistema" (desligado por padrão).
3. Fim: "Pronto. O DRACAENA fica na bandeja. Use o atalho ou o menu para ligar e desligar."

## Fluxo 2: assistente de atalhos (B2, textos de limitação)
Decide pelo ambiente (sessão X11/Windows/Wayland; compositor):
- **Windows e X11**: o app registra o atalho (B1/hotkeys). Campo de captura de tecla; erro de conflito: "Esse atalho já está em uso por outro programa. Escolha outro."
- **Wayland (qualquer compositor)**: "No Wayland o aplicativo não pode registrar um atalho global sozinho. Crie um atalho no seu sistema que execute este comando:" + `dracaena toggle` com botão Copiar e instruções por ambiente (comandos exatos vêm da pesquisa [PESQUISA] do Antigravity #2; não escrever antes de confirmar):
  - GNOME: Configurações → Teclado → Atalhos personalizados.
  - KDE Plasma: Configurações do sistema → Atalhos → Adicionar comando.
  - Hyprland: linha `bind` no `hyprland.conf` (mostrar linha pronta para copiar).
  - Sway: linha `bindsym`.
- Se o portal GlobalShortcuts estiver disponível (a confirmar na pesquisa), oferecer como alternativa.

## Fluxo 3: Adicionar site (B2, sobre `probe.start`)
1. Campo: "Endereço da página de prática" (URL). Botão "Verificar".
2. `probe.start` (pedido único; no simulado devolve `{matches, questions}`, sem eventos de progresso nem cancelamento): mostrar "Verificando…" sem bloquear a janela e, ao responder, o relato de quantos elementos cada seletor achou.
3. Sucesso: "Página reconhecida." O site em si é um perfil TOML (dono: Backend); como o perfil é gravado a partir do probe é PENDÊNCIA de CONTRATO (pedir ao Maestro; não inventar `sites.add`).
4. Falha: "Não consegui reconhecer as questões nessa página. Abra a atividade de prática no navegador e tente de novo." A UI nunca abre nem clica na página.

## Avisos de limitação (textos fixos)
- **Bandeja no GNOME**: "O GNOME não mostra ícones de bandeja por padrão. Instale e ative a extensão AppIndicator (AppIndicator and KStatusNotifierItem Support) ou use o atalho de teclado." (nome do pacote por distro: PENDENTE da pesquisa, não preencher sem fonte)
- **Bandeja no Hyprland**: "No Hyprland o ícone só aparece se a sua barra tiver o módulo de bandeja (tray) ativado."
- **Sem bandeja detectada**: "Não encontrei uma bandeja de sistema. O DRACAENA continua funcionando; abra as Configurações pelo atalho ou executando `dracaena settings`."
- **Atalho no Wayland**: ver fluxo 2.

## Roteiro de teste manual (esqueleto; o A1 completa por entrega)
Ambientes: Windows 11, GNOME (X11 e Wayland), KDE Plasma (Wayland), Hyprland. Para cada um: (1) abrir app, ícone aparece ou aviso certo; (2) menu e estados; (3) toggle por atalho/comando; (4) adicionar site; (5) autostart ligar/desligar; (6) fechar daemon e ver "sem conexão" e reconexão.
