# quiz-helper

Resolve, questão por questão, o quiz do Cisco NetAcad aberto no Vivaldi, sem você tocar em nada e sem calibração: a cada ciclo captura a janela inteira do navegador, acha sozinho o painel do quiz e a seta de avançar, consulta o Claude, marca a resposta (alternativa única, múltipla seleção, dropdowns e associação por arrasto), clica em **Submit**, trata o feedback de erro e avança até o fim. Feito para **Arch Linux + Hyprland (Wayland)**. Não usa nada de X11.

O botão que encerra a avaliação inteira ("Submit All", "Submit Assessment", "Finish"...) **nunca** é clicado. Quando ele aparece, o loop para e avisa que a avaliação está pronta para você enviar manualmente.

## Comandos

| Comando | O que faz | Atalho sugerido |
|---|---|---|
| `quiz-loop` | Liga/desliga o loop contínuo (toggle) | `SUPER+P` |
| `quiz-ask` | Uma questão, sem clicar: detecta o painel na janela do Vivaldi (ou, com `--select`, você seleciona a região) e mostra a resposta numa notificação e na área de transferência | `SUPER+SHIFT+P` |
| `quiz-doctor` | Diagnóstico do ambiente, com OK/FALHA e como corrigir | — |

Opções do `quiz-loop`:

- `--dry-run`: faz tudo, menos mover o cursor e clicar. Para cada questão, salva uma imagem anotada da janela inteira com o retângulo do painel detectado, a seta de avançar encontrada, uma cruz em cada clique planejado e uma seta em cada arrasto.
- `--replay <pasta>`: roda o loop inteiro sobre um cenário de teste (telas e respostas simuladas).
- `--stop`: só para o loop, se estiver rodando.
- `--status`: mostra se o loop está rodando, pausado ou parado.

## Requisitos

- Hyprland, `hyprctl`.
- Pacotes: `grim slurp tesseract tesseract-data-eng imagemagick ydotool libnotify wl-clipboard jq python glib2`.
- Claude Code instalado e logado (assinatura Pro ou superior). O modelo é chamado com `claude -p --model sonnet`, sem chave de API.
- Um daemon de notificação qualquer (mako, dunst, swaync...). Só o básico da especificação é usado: a notificação de status é substituída com `notify-send -p/-r` ou, se o libnotify não tiver `-p`, via `gdbus`.
- `ydotoold` rodando, com acesso ao `/dev/uinput`.

O `install.sh` lista o que falta, com o comando `pacman`, mas não instala nada sozinho.

## Instalação

```bash
git clone <url-do-repositório> ~/quiz-helper
cd ~/quiz-helper
./install.sh
```

O instalador é idempotente e faz quatro coisas:

- cria symlinks em `~/.local/bin` para os três comandos (e remove symlinks de comandos que deixaram de existir);
- copia a configuração padrão para `$XDG_CONFIG_HOME/quiz-helper/config`, só se ela ainda não existir;
- grava o caminho absoluto do `claude` em `$XDG_CONFIG_HOME/quiz-helper/paths`, porque os binds do Hyprland não carregam o `PATH` do shell interativo;
- mostra como ligar os atalhos. A config do Hyprland não é editada.

Config em Lua (`hyprland.lua`): copie `config/hyprland-binds.lua` para `~/.config/hypr/quiz-helper.lua` e carregue no fim do `hyprland.lua`:

```lua
do local chunk = loadfile(os.getenv("HOME") .. "/.config/hypr/quiz-helper.lua") if chunk then chunk() end end
```

Config clássica (`hyprland.conf`), em `config/hyprland-binds.conf`:

```
bind = SUPER, P, exec, ~/.local/bin/quiz-loop
bind = SUPER SHIFT, P, exec, ~/.local/bin/quiz-ask
```

### ydotool

Os cliques e a roda do mouse passam pelo `ydotool` (`click 0xC0`, `click 0x40/0x80` no arrasto, `mousemove --wheel -x 0 -y N` na rolagem). O cursor é posicionado pelo dispatcher do Hyprland, que usa coordenadas lógicas exatas e não sofre aceleração. Com a config em Lua, `hyprctl dispatch` interpreta o argumento como Lua, então o quiz-helper usa `hl.dsp.cursor.move({ x = X, y = Y })` e só cai para `dispatch movecursor X Y` em configs `hyprland.conf`. O socket do `ydotoold` é descoberto e exportado em `YDOTOOL_SOCKET` antes de cada chamada, porque os atalhos não herdam o ambiente do shell. Cada comando de entrada vai para o log da execução com o código de saída e o stderr completo; numa falha, a notificação de pausa mostra a primeira linha do erro real.

```bash
systemctl --user enable --now ydotool.service   # inicia o ydotoold agora e em cada login
sudo usermod -aG input "$USER"                  # acesso permanente ao /dev/uinput; vale após novo login
```

Se o `quiz-doctor` disser que o acesso ao `/dev/uinput` vem só por ACL da sessão, funciona, mas o grupo `input` é o caminho permanente.

Para desinstalar: `./uninstall.sh` remove só os symlinks que apontam para este repositório. Use `--purge` para apagar também a config e os logs.

## Primeiro uso

1. Abra uma questão de quiz no Vivaldi e rode `quiz-doctor`. Corrija o que estiver como FALHA. O doctor também testa a detecção sobre esse quiz e grava `$XDG_DATA_HOME/quiz-helper/doctor-detect.png` com a área de conteúdo, o painel e a seta encontrados.
2. Rode `quiz-loop --dry-run` em um "Check Your Understanding" de cada tipo (alternativa, dropdown e associação). Depois de cada questão, avance manualmente: o dry-run espera a questão mudar. Confira as imagens anotadas `dryrun.png` em `$XDG_DATA_HOME/quiz-helper/runs/<data>-dryrun/qNNN/`.
3. Se o arrasto da associação não funcionar no seu navegador, use `MATCH_MODE=click`. O loop já tenta o outro modo sozinho uma vez antes de pausar.
4. Rode sem a flag: `SUPER+P` liga, e `SUPER+P` de novo desliga.

## Detecção automática da página

Não há calibração e nada é guardado entre execuções. A cada captura:

1. **Janela**: confere que a janela ativa é o Vivaldi (`BROWSER_CLASS_REGEX`) com o monitor ligado. Se não for, pausa com "Deixe o Vivaldi com o quiz em foco". Depois captura a janela inteira com `grim -g "<at> <size>" -s <escala do monitor dela>` (timeout de 10 s). Todas as coordenadas são relativas a essa captura e convertidas na hora para coordenadas de tela. Mover ou redimensionar a janela no meio do loop não quebra nada: se ela mudou entre a captura e um clique, o loop não clica e captura de novo.
2. **Área de conteúdo**: descarta a interface do Vivaldi (abas, barra de endereço, faixa e painel lateral, barra de status) achando as bordas retas que atravessam a janela inteira. A coluna de módulos do NetAcad também cai fora quando tem borda de altura total. Se errar, fixe as margens com `CHROME_TOP_PX` e `CHROME_LEFT_PX` (pixels lógicos; padrão `auto`).
3. **Painel do quiz**: um único OCR da área de conteúdo procura âncoras: "Question N", "Check Your Understanding", enunciados com "Match" ou "Choose", o botão Submit e alternativas com rádio/checkbox. O retângulo cresce por proximidade do título da questão até abaixo do Submit e das alternativas. Ficam de fora a lista de módulos do NetAcad (a coluna com "1/1", "2/2", porcentagens) e a barra Q1…Qn. O recorte do painel reaproveita esse OCR; as capturas de conferência logo depois de um clique reaproveitam também o enquadramento.
4. **Seta de avançar**, nesta ordem e só com exatamente um candidato:
   - (a) o chevron ">" logo à direita da barra Q1 Q2 … Qn. A barra é uma fileira de bolhas iguais em passo regular, confirmada pelo OCR dos rótulos ou por ter cinco ou mais bolhas; o chevron é reconhecido pela forma, nos pixels.
   - (b) o botão de borda verde com ">" na lateral direita do painel: contorno verde vazado com um chevron apontando para a direita.
5. **Envio ao Claude**: vai só o recorte do painel, que é mais rápido e evita que a lista de módulos confunda a resposta. No `quiz-ask`, se o painel não for detectado, vai a área de conteúdo inteira, e isso fica registrado no log.

**Quando a detecção falha**:
- **Painel não encontrado em duas capturas seguidas**: o loop pausa com uma notificação sugerindo rolar até o topo da questão e segue sozinho quando o painel volta a aparecer.
- **Seta não encontrada**: a notificação pede "Não achei a seta de avançar. Clique nela uma vez." e captura o seu clique com `slurp -p`. O ponto fica só em memória, relativo ao canto superior direito do painel detectado, e é reutilizado enquanto o loop rodar, sempre depois de uma nova tentativa de detecção automática. Na próxima execução, a detecção automática é tentada de novo. Esc cancela o pedido: o loop pausa e segue quando você avançar à mão.

## Como o loop funciona

Cada questão passa por estas etapas:

1. **Estabiliza**: captura a janela do Vivaldi duas vezes, com intervalo `STABLE_INTERVAL_MS`, até a diferença (`magick compare -metric AE`) ficar abaixo de `STABLE_TOLERANCE_PX`.
2. **Detecta e identifica**: acha o painel (veja acima) e lê "Question N" e o título por OCR, mais um hash da imagem. Se a questão for a mesma de antes, espera mudar até `ADVANCE_TIMEOUT`.
3. **Consulta o Claude** com o prompt de `prompts/answer.txt` (com `timeout CLAUDE_TIMEOUT`) e valida o JSON. Se não for válido, repete uma vez; se falhar de novo, pausa.
4. **Rola, se precisar**: se o Claude responder `INCOMPLETE`, ou se alternativas, itens ou o Submit não aparecerem, rola com a roda do mouse até `MAX_SCROLLS` (primeiro para baixo, depois para cima). Depois de rolar, todas as coordenadas são recalculadas a partir de uma captura nova.
5. **Responde**:
   - **SINGLE e MULTI**: localiza a alternativa por OCR e similaridade (`difflib`, `MATCH_THRESHOLD`) e clica `CLICK_OFFSET_X` px à esquerda do texto. Na múltipla seleção, lê o estado de cada checkbox antes de clicar (não desmarca o que já está certo, desmarca o que está errado) e confere a quantidade com `expected`.
   - **DROPDOWN**: para cada item, localiza o enunciado e o dropdown logo abaixo (ou à direita), abre, espera `DROPDOWN_DELAY_MS`, acha a opção exata entre as linhas que apareceram e clica. Depois confere o valor exibido e tenta de novo uma vez.
   - **MATCH**: acha o círculo tracejado à esquerda de cada item da direita e o círculo colorido da letra (OCR da letra, com o texto do item da esquerda como conferência). Em seguida, arrasta (`drag`: `ydotool click 0x40`, movimento em passos, `0x80`) ou clica letra e alvo (`click`). Confere a ligação e, se ela não aparecer, tenta o outro modo uma vez. Funciona nas duas variantes: letras com descrições e "Categories/Options".
6. **Submit**: só clica se houver **exatamente uma** linha com a palavra "Submit" isolada e confiança do OCR acima de `OCR_MIN_CONF`. Recusa (e pausa) se houver outra palavra na linha ou mais de um Submit.
7. **Feedback**: procura frases novas de `FEEDBACK_INCORRECT_WORDS` e `FEEDBACK_CORRECT_WORDS`. Se a resposta estiver errada, consulta o Claude com a captura do feedback (`prompts/retry.txt`), usa o botão Reset/Try again se existir, refaz uma única vez e avança.
8. **Avança**: depois de `NEXT_DELAY_MS`, clica na seta detectada (ou no ponto informado por você, veja o fallback acima).
9. **Encerra** quando:
   - a página não muda após avançar;
   - aparece uma tela final (`END_WORDS`) ou o botão de envio da avaliação;
   - chega a `MAX_QUESTIONS`.

   O resumo mostra quantas questões foram respondidas automaticamente, quantas com retry, quantas esperaram por você, as recusas e o tempo total.

### Segurança

Toda localização abaixo do limiar ou ambígua termina numa **pausa manual**: nada é clicado, a notificação mostra a resposta (que também vai para a área de transferência) e o loop segue sozinho quando detecta que você mudou de questão.

**Parada de emergência**: se o cursor estiver a mais de `MOUSE_ABORT_PX` de onde o script o deixou, o loop pausa na hora, inclusive durante a consulta ao Claude. Aperte `SUPER+P` para retomar a partir da questão atual.

Antes de cada clique, o loop confere que a janela ativa ainda é o Vivaldi; se não for, pausa. Também confere que posição e tamanho da janela são os da captura usada; se mudaram, não clica e captura de novo.

Outras proteções:
- Toggle por PID file em `$XDG_RUNTIME_DIR/quiz-helper`, com `flock` impedindo dois loops ao mesmo tempo.
- A notificação de status é sempre substituída, nunca empilhada.

## Configuração

O arquivo é `$XDG_CONFIG_HOME/quiz-helper/config`, no formato `KEY=VALUE`, e cada chave está comentada nele. Ordem de precedência: padrões do repositório (`config/quiz-helper.conf`) < `paths` (gerado pelo instalador) < sua config.

| Chave | Padrão | Uso |
|---|---|---|
| `MODEL` | `sonnet` | modelo do `claude -p --model` |
| `CLAUDE_TIMEOUT` | `45` | segundos por chamada |
| `BROWSER_CLASS_REGEX` | `^vivaldi` | regex do `class` da janela (no Arch: `vivaldi-stable`) |
| `CHROME_TOP_PX`, `CHROME_LEFT_PX` | `auto` | margens fixas (px lógicos) da interface do Vivaldi, se a detecção errar |
| `NOTIFY_OVER_DND` | `1` | com "não perturbe" ligado, envia as notificações como críticas para aparecerem |
| `CLICK_OFFSET_X` | `40` | px lógicos à esquerda do texto da alternativa |
| `MATCH_THRESHOLD` | `0.6` | similaridade mínima para aceitar um texto |
| `OCR_MIN_CONF` | `60` | confiança mínima do OCR no "Submit" |
| `CLICK_SUBMIT` | `1` | `0` = não clica em Submit |
| `SUBMIT_DELAY_MS`, `DROPDOWN_DELAY_MS`, `FEEDBACK_DELAY_MS`, `NEXT_DELAY_MS`, `STABLE_INTERVAL_MS` | 300, 350, 800, 800, 400 | esperas |
| `ADVANCE_TIMEOUT` | `8` | segundos esperando a questão mudar |
| `MAX_QUESTIONS` | `60` | por execução |
| `MAX_SCROLLS` | `6` | rolagens por busca e direção |
| `SCROLL_STEP` | `-3` | cliques da roda por rolagem (inverta o sinal se rolar ao contrário) |
| `MOUSE_ABORT_PX` | `30` | parada de emergência |
| `MATCH_MODE` | `drag` | `drag` ou `click` |
| `RETRY_ON_INCORRECT` | `1` | refazer uma vez após feedback de erro |
| `SUBMIT_WORDS_BLOCKLIST` | `all,assessment,exam,finish,end` | identificam o botão final, que nunca é clicado |
| `FEEDBACK_CORRECT_WORDS` | `Correct,You answered correctly,...` | frases de acerto |
| `FEEDBACK_INCORRECT_WORDS` | `Incorrect,Partly correct,...` | frases de erro (têm prioridade) |
| `END_WORDS` | `Assessment Complete,Your score,...` | tela final |
| `RESET_WORDS` | `Reset,Try again,Retry` | botão de desfazer antes do retry |
| `KEEP_DAYS` | `7` | retenção das capturas |

**Termos de feedback.** O conteúdo do NetAcad usa componentes do framework Adapt, cujo feedback traz o título "Correct", "Incorrect" ou "Partly correct". Os padrões cobrem esses títulos e variações comuns ("You answered correctly", "That's not right", "Try again"). Só frases que **surgem** depois do Submit contam, então "correct" no enunciado não é confundido com feedback. Como os textos podem variar por curso, confira numa questão real e ajuste as listas se precisar. Provas normalmente não mostram feedback; nesse caso o loop só segue.

Os prompts ficam em `prompts/answer.txt` e `prompts/retry.txt` e podem ser editados sem mexer em código. Os marcadores `{IMAGE}` e `{PREVIOUS}` são substituídos na hora da chamada.

## Logs e auditoria

Tudo fica em `$XDG_DATA_HOME/quiz-helper/runs/<data-hora>/`:
- `run.log` com a execução inteira;
- `qNNN/log.txt` por questão: data e hora, número, tipo, JSON do Claude, tempo do Claude, cada clique com coordenadas, rolagens, retry, recusas e motivos;
- `qNNN/cap-*.png` com todas as capturas da janela, antes e depois de responder, junto com os recortes `*.content.png` (área de conteúdo) e `*.panel.png` (painel);
- cada comando de entrada (cursor, `ydotool`) com código de saída e stderr.

Capturas com mais de `KEEP_DAYS` dias são apagadas no início de cada execução.

## Testes

```bash
tests/run.sh                      # shellcheck + unittest + entrada + replay
tests/run.sh --only unit          # só os testes unitários
tests/replay/run.sh multi_flow    # um cenário de replay
tests/bench-claude.sh 3           # tempo médio do claude -p (consome cota)
```

Nenhum teste clica de verdade nem chama o Claude, exceto o benchmark.

- **Telas sintéticas**: `tests/fixtures/make_fixtures.py` gera, com o ImageMagick, telas no estilo do NetAcad (em `tests/fixtures/out/`, ignorada pelo git). Cada tela vem com um gabarito `.truth.json` das posições desenhadas.
  - **Janelas inteiras** do Vivaldi (`win_*.png`): barra de abas e endereço, faixa lateral e painel lateral aberto ou fechado, cabeçalho e lista de módulos do NetAcad, barra Q1…Q10 com chevrons e botões verdes laterais. Cada questão é colada nesse quadro. Há variantes de seta (as duas, só a barra, só o botão verde, nenhuma) e escala 2.
  - **Painéis de questão**, cobrindo:
  - SINGLE, inclusive em escala 2;
  - MULTI sem e com item marcado;
  - DROPDOWN fechado e aberto;
  - MATCH nas duas variantes, inclusive com borda escura atravessando os círculos;
  - "Submit" isolado, "Submit All" e dois "Submit";
  - feedback correto e incorreto, e a tela final.
- **Unitários** (`tests/unit/`, `unittest`): validam contra o gabarito cada função de localização e a detecção da página (área de conteúdo, painel sem a lista de módulos, ordem e unicidade da seta, escala 1 e 2, painel lateral aberto, tela final sem painel). Também cobrem contrato, configuração, geometria multi-monitor com escala, decodificação de PNG/PPM e a máquina de estados: janela que mudou antes do clique, painel ausente e o fallback da seta relativo ao painel.
- **Entrada** (`tests/input/run.sh`): `lib/sh/input.sh` com `ydotool` e `hyprctl` simulados. Cobre sucesso com dispatch Lua e com a sintaxe antiga, socket ausente, daemon recusando conexão e sintaxe inválida. O erro real precisa chegar ao log e à mensagem de pausa.
- **Replay** (`tests/replay/*/scenario.json`): roda o `quiz-loop` real com capturas da janela inteira e respostas do Claude simuladas, com a janela em posições globais diferentes. Cliques de avançar fora da seta esperada contam como falha, e há um limite de passos para um cenário preso nunca travar os testes. Cobre:
  - troca de questão;
  - rolagem (`INCOMPLETE`);
  - retry com Reset;
  - pausa por ambiguidade, com retomada sozinha;
  - recusa de dois Submit;
  - "Submit All" nunca clicado;
  - fim por tela final, por página parada e por `MAX_QUESTIONS`;
  - fallback da seta: o usuário clica no ponto, ou cancela com Esc;
  - um tour em `--dry-run` que confere as imagens anotadas.

## quiz-doctor

Verifica o ambiente e mostra, para cada falha, o comando de correção:
- dependências e seus pacotes `pacman`;
- idioma `eng` do tesseract;
- acesso ao `/dev/uinput` (grupo `input` ou ACL) e `ydotoold`;
- daemon de notificação e suporte a `-p`;
- Hyprland, monitores e escalas;
- janela do navegador que casa com `BROWSER_CLASS_REGEX`;
- config, prompts e symlinks;
- caminho do `claude`, login (`claude auth status`), diretório temporário do claude e um teste de OCR;
- **ambiente dos atalhos**: roda a mesma sonda (`lib/sh/env-probe.sh`: mover o cursor, `ydotool click 0x00`, roda com deslocamento 0, `claude -p` mínimo) no terminal e via `hyprctl dispatch exec`, como um atalho. Aponta o que funciona num e falha no outro, com o erro real. Os dois bugs que só apareciam pelos atalhos, `/tmp/claude-1000` e o dispatch em Lua, teriam sido pegos aqui;
- **detecção**: se houver um Vivaldi aberto, traz a janela para a frente por um instante (e devolve o foco), captura, roda a detecção e informa se achou o painel e a seta. A imagem anotada vai para `$XDG_DATA_HOME/quiz-helper/doctor-detect.png`.

## Estrutura

```
bin/              comandos do usuário (bash; só orquestram)
lib/sh/           bibliotecas bash: config, notificação, Hyprland, captura, entrada, claude
lib/quizvision/   pacote Python (stdlib): PNG, OCR, análise de página, detecção da página,
                  contrato, geometria, máquina de estados, anotação, simulador de replay
lib/quizvision/locate/  localização, um módulo por capacidade: área de conteúdo, painel,
                  seta de avançar, alternativas, dropdowns, associação, botões e feedback
config/           configuração padrão comentada e atalhos do Hyprland (Lua e .conf)
prompts/          prompts do Claude (resposta e retry)
tests/            runner, benchmark, fixtures sintéticas, unitários, entrada (com mocks
                  de ydotool/hyprctl) e cenários de replay
install.sh        instalação idempotente (symlinks, config inicial, caminho do claude)
uninstall.sh      remoção idempotente
```

O bash executa (captura, cliques, notificações, chamada ao Claude). O Python decide: `quizvision step` recebe cada evento e devolve a próxima ação. Toda a lógica de visão é testável sem Hyprland e sem cliques.

## Limitações conhecidas

- **Só OCR em inglês** (`eng`): os textos precisam estar visíveis no painel. Imagens dentro da questão ("Refer to the exhibit") vão para o Claude, mas o loop não as interpreta.
- **Feedback em popup modal** que exige fechar antes de avançar não é tratado. Se a seta não avançar, o loop encerra por página parada.
- **Dropdowns nativos** (`<select>`) que o navegador abre como janela separada, fora da captura, não são lidos. Nesse caso o loop pausa mostrando a resposta.
- **Associação**: depende dos círculos (letra colorida à esquerda, alvo tracejado à direita). Layouts diferentes pausam para você fazer à mão.
- **Botão final sempre visível**: se o botão de envio da avaliação aparecer em todas as páginas, o loop encerra logo de início, por segurança.
- **Detecção heurística**: âncoras em inglês ("Question", "Submit", "Match", "Choose"). Interfaces muito diferentes da testada exigem `CHROME_TOP_PX`/`CHROME_LEFT_PX` ou caem no fallback (pausa, ou clique pedido para a seta). Confira com o `quiz-doctor` e o `--dry-run`.
- **Desempenho**: cada captura da janela leva ~2,5 s de detecção e OCR em escala 1 (~7 s em escala 2). As capturas de conferência reaproveitam o enquadramento e são mais rápidas. A consulta ao Claude leva ~5 s por questão, medidos com `sonnet` em imagens de teste.
- **Rolagem**: a direção da roda no `ydotool` pode variar. Ajuste o sinal de `SCROLL_STEP` se a página rolar ao contrário.
- **Rolagem manual durante uma pausa**: em questões sem número ("Question N"), rolar a página manualmente para uma vista ainda não vista pode ser interpretado como troca de questão.
- **Wayland/Hyprland apenas**: depende de `hyprctl`, `grim` e `slurp`.
