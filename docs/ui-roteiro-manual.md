# Roteiro de teste manual da UI (para o humano)

Rascunho do A1 - FrontEnd, 2026-11-10. Marcas: **OK esperado** = comportamento que a entrega deve ter; **NÃO CONFIRMADO** = depende de fato externo que ninguém verificou na prática; **NÃO VALIDADO** = nenhum teste real foi feito neste ambiente. Anote ao lado de cada passo: passou, falhou ou não deu para testar, e o que viu.

Cada ambiente começa igual. Para testar sem navegador, use o daemon simulado: `dracaena daemon --simulate` (a UI nunca fala com a página; o simulado usa uma página falsa).

## 0. Passos comuns (todos os ambientes)
1. Abra o app (AppImage no Linux, instalador no Windows). **OK esperado:** nenhuma janela abre; aparece um ícone na bandeja, ou um aviso claro de que não há bandeja.
2. Sem site configurado, abra o menu da bandeja → **OK esperado:** "Adicionar site" em destaque e a primeira execução abre sozinha na primeira vez.
3. Passe o mouse no ícone → a dica mostra estado e site (parado, rodando, pausado, erro) e, rodando, "questão n de N".
4. Menu → **Iniciar**: o ícone muda para rodando. **Pausar**: pausado; **Retomar**: volta; **Parar**: parado. Itens que não valem no estado atual aparecem desabilitados.
5. **Responder só esta questão** envia `ask`; **Diagnóstico** abre o resultado do `doctor` (nenhum clique na página parte da UI).
6. Finalize o daemon à força (`pkill -f "dracaena daemon"`). **OK esperado:** em poucos segundos o ícone indica "sem conexão"; ao subir o daemon de novo, reconecta sozinho, sem reiniciar a UI.
7. Abra **Configurações**. **OK esperado:** campos vêm todos de `config.schema` (nome, tipo, padrão, faixa). Digite um valor fora da faixa → erro legível e nada é gravado. Altere um valor válido, feche e reabra → o valor persiste.
8. **Adicionar site:** informe o endereço de uma página de prática salva/local → "Verificando…" sem travar a janela → resultado com quantos elementos cada seletor achou; **Cancelar** durante a verificação interrompe. Salvar grava via `sites.save`; o site aparece na lista.
9. **Iniciar com o sistema** (opt-in, desligado por padrão): ligue, saia da sessão e entre de novo → o app sobe sozinho; desligue e repita → não sobe.
10. Abra o app uma segunda vez → **OK esperado:** a segunda instância avisa e sai (lock), a primeira continua.

## 1. Windows 11 (**NÃO VALIDADO**: nenhum teste nativo foi feito até aqui)
- Atalho global (padrão sugerido na UI): grave um atalho no assistente e pressione-o com outro programa em foco → alterna o estado. Conflito (atalho já usado pelo sistema ou outro programa) → mensagem "Esse atalho já está em uso por outro programa. Escolha outro.".
- Autostart pelo registro (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`): confira no Gerenciador de Tarefas → Inicializar.
- Bandeja: o ícone pode ficar em "ícones ocultos"; confirme que o menu abre com clique direito.
- Instalador sem assinatura: o SmartScreen avisa; isso é esperado e não é bug da UI.

## 2. GNOME
Variações: sessão **Xorg** e sessão **Wayland**.
- Sem a extensão AppIndicator, o ícone **não aparece**. **OK esperado:** a UI mostra o aviso do GNOME (extensão AppIndicator ou uso do atalho) em vez de falhar calada. Instale e ative a extensão, reinicie a sessão e confirme que o ícone aparece. O nome do pacote por distro **não foi confirmado**: registre qual funcionou.
- **Xorg:** o atalho é registrado pelo app (X11) → alterna o estado.
- **Wayland:** o app **não** registra atalho global. O assistente mostra o comando de `hello.toggle_cmd` e oferece criar o atalho personalizado do GNOME. **OK esperado:** mostra exatamente o que gravará, pede confirmação, **acrescenta** à lista de atalhos existentes (confira antes e depois com `gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings`: os seus atalhos antigos continuam lá). Teste o atalho criado.
- Portal GlobalShortcuts no GNOME 48 ou mais novo: **NÃO CONFIRMADO**. Se o app oferecer essa via, anote se funcionou.

## 3. KDE Plasma (Wayland e X11)
- Bandeja: nativa; confirme ícone e menu.
- Wayland: o assistente guia o caminho manual (Configurações do sistema → Atalhos → Adicionar comando) com o comando de `hello.toggle_cmd`. Siga o texto à risca e confirme que o atalho dispara. **NÃO CONFIRMADO:** criação automática por arquivo `.desktop`/`kglobalshortcutsrc`; a UI não faz isso.
- Portal GlobalShortcuts: **NÃO CONFIRMADO** a partir de qual versão do Plasma; anote a sua versão e o resultado.

## 4. Hyprland
- Bandeja: só aparece se a barra tiver o módulo de bandeja ativado. **OK esperado:** sem ele, o aviso do Hyprland aparece. Ative o módulo `tray` da sua barra e confirme que o ícone surge sem reiniciar o app (se exigir reiniciar, anote).
- Atalho: o assistente mostra a linha `bind = ..., exec, <comando>` para o `hyprland.conf` (copiável). Cole, recarregue (`hyprctl reload`) e teste.
- Atalho global do próprio app no Wayland: não existe; é esperado.

## 5. Sway (se usar)
- Bandeja depende da barra (swaybar com tray). Atalho: linha `bindsym ... exec <comando>`; o app não registra atalho.

## 6. AppImage
- Em AppImage, o comando do atalho deve apontar para o `$APPIMAGE` (arquivo real), nunca para o ponto de montagem temporário. Confira: feche o app, dispare o atalho → deve funcionar mesmo assim (o comando inicia/alterna o daemon). **NÃO CONFIRMADO** até o Backend implementar `hello.toggle_cmd`.

## O que registrar
Distribuição e versão (ou Windows 11 build), sessão (Xorg/Wayland), versão do GNOME/Plasma/Hyprland, passo, resultado, captura de tela se falhar.
