# dracaena / quiz-helper

Ferramenta local para ler atividades do NetAcad pelo DOM, consultar o Claude Code e aplicar respostas pelo Playwright, conectado ao Vivaldi via Chrome DevTools Protocol (CDP). Os comandos continuam se chamando `quiz-helper`/`quiz-*`.

O ambiente de uso validado é Linux com Hyprland e Vivaldi. Outros sistemas e navegadores não foram validados. A implementação anterior de OCR permanece em `lib/quizvision` e `lib/sh`; não é o motor dos comandos atuais.

## Requisitos

- Python 3.10+ com `venv` e pip; validação local realizada com Python 3.14.
- Bash, `curl`, `ss`, `flock`, `setsid` e utilitários básicos do Linux.
- Vivaldi instalado, executável padrão `vivaldi-stable`.
- Claude Code instalado e autenticado (`claude auth login`).
- Playwright na versão declarada em `requirements.txt`.
- Opcional: `notify-send` e um daemon de notificações; `wl-copy` para copiar a resposta; Hyprland para os atalhos fornecidos.

OCR, Tesseract, ImageMagick, `grim`, `slurp`, `ydotool` e `/dev/uinput` pertencem ao modo legado. Não são necessários para responder pelo DOM.

## Instalação

```bash
git clone https://github.com/Pedrojscx/dracaena.git
cd dracaena
./install.sh --check
./install.sh
```

O instalador cria `${XDG_DATA_HOME:-$HOME/.local/share}/quiz-helper/venv`, instala somente `requirements.txt` (e suas dependências transitivas) e cria os quatro symlinks em `~/.local/bin`. Reexecutá-lo aplica as versões declaradas sem sobrescrever a configuração pessoal. Ele não usa sudo, não instala pacotes do sistema e não baixa navegadores. Acesso ao índice pip é necessário na primeira instalação, salvo uso de um cache/índice local.

O arquivo padrão `config/quiz-helper.conf` é copiado para `${XDG_CONFIG_HOME:-$HOME/.config}/quiz-helper/config` apenas se ainda não existir. Caminhos resolvidos ficam no arquivo local `paths`. Se já houver configuração antiga, revise-a manualmente. Não publique esses arquivos pessoais.

O Playwright controla o Vivaldi já instalado por CDP. O Chromium fornecido pelo Playwright é usado **somente nos testes da guarda** e é instalado separadamente, de forma explícita.

## Primeiro uso

```bash
quiz-browser
# Faça login no NetAcad nesse Vivaldi e abra uma única aba /launch com uma atividade.
quiz-doctor
quiz-loop --dry-run
```

O perfil dedicado fica em `${XDG_DATA_HOME:-$HOME/.local/share}/quiz-helper/vivaldi-profile`. O login do NetAcad é feito manualmente nesse perfil. A tela inicial da avaliação também exige ação manual antes de iniciar o loop.

`--dry-run` lê a questão e pode consultar o Claude (consumindo cota), mas a guarda simula as ações sem clicar. Depois da simulação o loop pausa. `quiz-loop --stop` encerra o processo; uma execução posterior sem `--dry-run` inicia o modo normal.

Os atalhos opcionais estão em `config/hyprland-binds.conf` e `config/hyprland-binds.lua`. A instalação não edita o Hyprland automaticamente.

## Comandos

| Comando | Comportamento |
|---|---|
| `quiz-browser [URL]` | Abre o perfil dedicado, ou abre uma aba no navegador CDP já disponível |
| `quiz-browser --status` | Verifica escuta em loopback e `/json/version`; não abre abas |
| `quiz-loop` | Inicia; se já estiver rodando, alterna pausa/retomada |
| `quiz-loop --status` | Informa se o loop está rodando |
| `quiz-loop --stop` | Pede o encerramento do loop |
| `quiz-loop --once` | Processa somente uma questão |
| `quiz-loop --dry-run` | Consulta e simula as ações, sem clicar |
| `quiz-ask` | Consulta a questão atual, notifica e copia a resposta se houver `wl-copy`; não clica |
| `quiz-doctor` | Diagnóstico DOM somente leitura, sem consultar questões ao Claude |
| `quiz-doctor env` | Diagnóstico opcional com consultas sintéticas terminal/Hyprland; consome cota |

`quiz-browser` não possui `--stop` ou `--restart`. Feche o Vivaldi dedicado pela interface do navegador quando terminar.

## Como a página é lida

O Playwright conecta a `127.0.0.1:CDP_PORT`, encontra a aba NetAcad `/launch` e o iframe `authoring-resources/index.html`. O leitor percorre o DOM e os shadow roots abertos. Nas avaliações, a questão atual vem da faixa de navegação e do contador; nas seções do curso, do bloco correspondente ao item indicado no título da aba.

Componentes reconhecidos:

- `mcq-view`: resposta única ou múltipla.
- `matching-view` / `matching-dropdown-view`: listas de seleção.
- `object-matching-view`: associação de itens.

Figuras relevantes são capturadas dos elementos da questão, quando necessário, e enviadas com o texto ao Claude. A falta de uma figura exigida causa pausa. O contrato valida os índices e a quantidade de respostas antes de aplicar ações.

Os títulos `Module Exam`, `Checkpoint Exam` e `Final Exam` não são bloqueados. A mudança de atividade continua causando pausa. O título do iframe não é consultado para decidir se a atividade pode ser processada.

## Proteções e configuração

A guarda centraliza os cliques. A tela `finalscreen-view`, o envio final da avaliação, a confirmação de envio, Skip All e Skip Question permanecem bloqueados. O envio final é manual. A guarda também restringe ações ao componente atual e verifica o alvo antes de agir.

`CLICK_SUBMIT=1` permite o Submit da questão atual; `CLICK_SUBMIT=0` marca e pausa, sem enviar a questão. Isso não autoriza envio final. As regras de clique e esse comportamento não foram alterados na preparação para publicação.

Os padrões completos estão em `config/quiz-helper.conf`. Entre eles: `MODEL=haiku`, `RETRY_MODEL` vazio, `CDP_PORT=9222`, `BROWSER_BIN=vivaldi-stable`, limites de espera e `KEEP_DAYS=7`. O modelo e os prompts fazem parte da implementação atual; configure preferências no arquivo pessoal, não em arquivos de sessão versionados.

## Registros e privacidade

As execuções ficam em `${XDG_DATA_HOME:-$HOME/.local/share}/quiz-helper/runs/`. Podem conter questões, respostas, prompts, saída do Claude, figuras e logs. Novas pastas são criadas com `700` e novos arquivos sensíveis com `600`. Permissões de arquivos antigos não são alteradas automaticamente; revise-as manualmente se necessário.

O `quiz-loop` remove diretórios de execução com idade superior ao limite de `KEEP_DAYS` ao iniciar uma nova execução. Não há limpeza agendada independente. O runtime usa `$XDG_RUNTIME_DIR/quiz-helper` ou `/tmp/quiz-helper-UID` e contém locks, PID e diretórios temporários do Claude.

O diagnóstico registra apenas `definida` ou `ausente` para variáveis de credencial. Não compara nem grava o valor de tokens/senhas/cookies. Os relatórios continuam privados e ignorados pelo Git, pois podem conter caminhos locais e saídas de diagnóstico.

A porta CDP permite controlar o perfil autenticado. Mesmo limitada ao loopback, processos locais com acesso à porta podem controlá-lo. Não exponha, encaminhe ou compartilhe essa porta. O lançador recusa escuta fora de `127.0.0.1` e serviços que não respondem como CDP. A validação do protocolo não autentica o processo que ocupa a porta; o doctor também confere o processo com o perfil dedicado.

## Diagnóstico e limitações

`quiz-doctor` verifica venv, Playwright, Claude e seu estado de autenticação, prompts, configuração, symlinks, perfil, porta, endpoint CDP, aba, iframe e leitura da questão. Ele não imprime o enunciado, não captura figuras, não clica e não fecha o navegador. Notificações e clipboard são opcionais.

Se a autenticação do Claude expirar, pause o loop, execute `claude auth login` no terminal e repita `quiz-doctor`. Se a sessão do NetAcad expirar, entre novamente no perfil aberto por `quiz-browser`. Depois volte à atividade e retome manualmente.

Mudanças no DOM do NetAcad, componentes não suportados, mais de uma aba compatível, navegação durante uma ação e respostas inválidas podem impedir o processamento. O helper não garante acerto das respostas. Apenas o fluxo DOM foi mantido como suíte padrão; os testes de replay antigos esperam opções removidas do lançador atual e ainda precisam de atualização.

## Testes locais

Instale ShellCheck pelo gerenciador do sistema. Prepare o navegador **de teste** explicitamente:

```bash
PYTHON="${XDG_DATA_HOME:-$HOME/.local/share}/quiz-helper/venv/bin/python"
"$PYTHON" -m pip install -r requirements-dev.txt
"$PYTHON" -m playwright install --only-shell chromium
tests/run.sh
```

A suíte padrão executa sintaxe Bash, ShellCheck, compilação Python, contrato, guarda, recuperação, erros do Claude, credenciais, permissões, CDP, lançador e instalação. Usa fixtures sintéticas, mocks dos comandos externos e HOME/configuração temporários. Não acessa conta real, não chama o Claude real e não usa o perfil do Vivaldi. O teste da guarda usa Chromium headless e um servidor HTTP em loopback; um sandbox que bloqueie sockets ou não tenha o navegador pode impedir essa parte.

Para um venv de desenvolvimento alternativo: `QH_PYTHON=/caminho/do/venv/bin/python tests/run.sh`.

A implementação e os testes legados continuam disponíveis:

```bash
tests/run.sh --legacy
# Ou somente partes:
tests/run.sh --legacy --only unit
tests/run.sh --legacy --only input
```

O legado requer as ferramentas de OCR e pode apresentar falhas de compatibilidade com a configuração/CLI DOM. Não é executado pela CI padrão. O diagnóstico antigo foi preservado em `lib/sh/doctor-legacy.sh` para referência; contém verificações visuais e não tem as garantias do doctor DOM.

A GitHub Action instala as ferramentas de teste e executa a mesma suíte sem conta real. A busca de credenciais em `tests/check_publication.py` detecta padrões comuns e arquivos cobertos pelo `.gitignore`; não substitui revisão humana do conteúdo ou histórico.

## Publicação

Versione código, configuração padrão, prompts e geradores sintéticos. Mantenha fora do Git perfis, cookies, sessões, `.env`, configurações pessoais, venvs, `runs/`, capturas, snapshots reais, relatórios, caches e `graphify-out/`. Não use `git add -f` para esses dados.

Não foi escolhida uma licença para o projeto nesta etapa.
