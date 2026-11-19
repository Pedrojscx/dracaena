# Dracaena 0.1.0 — AppImage Linux x86_64 (pré-release de teste)

Esta release é a primeira distribuição do Dracaena em um único arquivo executável
para Linux. Ela vem da branch `release/appimage-v0.1.0`, usada para testes antes da
integração na `main`. **Não é uma versão estável.**

## O que vem no pacote

| Item | Versão |
| --- | --- |
| CLI `dracaena` (daemon, loop, ask, toggle, stop, status, doctor, probe, once, install-browser) | 0.1.0 |
| Python embutido | 3.12.8 |
| Playwright e driver | 1.64.1 |
| Chromium embutido (Chrome for Testing) | 156.0.8078.4 (revisão 1248) |
| Runtime AppImage | type2-runtime `20251108` (estático, sem `libfuse2`), squashfs zstd |
| Base de build | `quay.io/pypa/manylinux_2_28_x86_64` (AlmaLinux 8, glibc 2.28), digest `sha256:d086f64c…fd2c` |

As versões e os SHA-256 de Python, PyInstaller, das dependências pip, do Playwright,
do Chromium, do runtime e do appimagetool estão fixados. Os pacotes `apt` da imagem
de build não estão fixados, então o build não garante identidade bit a bit.

O daemon real (núcleo + serviço) está incluído. Por padrão ele roda em modo
simulação (`DRY_RUN`) e não clica na página.

Não entram neste pacote: interface gráfica Qt, bandeja do sistema e atalho global
X11 (`python-xlib`). Eles continuam disponíveis só pela instalação a partir do código.

## Instalação

```bash
chmod +x dracaena-x86_64.AppImage
./dracaena-x86_64.AppImage --version
./dracaena-x86_64.AppImage doctor
```

Sem FUSE (contêineres, WSL, algumas distribuições mínimas) o AppImage também roda por extração:

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./dracaena-x86_64.AppImage --version
# ou
./dracaena-x86_64.AppImage --appimage-extract-and-run --version
```

**Resíduo da extração.** O AppImage extrai o pacote (cerca de 600 MB) em
`$TMPDIR/appimage_extracted_<md5 do arquivo>` (padrão `/tmp`) e **não o apaga ao sair**. As execuções seguintes
reaproveitam o diretório (0,6 s em vez de 2,4 s no `--version`), e cada versão nova do AppImage deixa outro
diretório. Em muitos sistemas `/tmp` fica na memória: se faltar RAM, aponte `TMPDIR` para um disco
(`TMPDIR=$HOME/.cache/dracaena APPIMAGE_EXTRACT_AND_RUN=1 ./dracaena-x86_64.AppImage ...`). Para liberar o espaço,
com o Dracaena fechado (`dracaena stop`), na pasta do arquivo:

```bash
rm -rf "${TMPDIR:-/tmp}/appimage_extracted_$(md5sum dracaena-x86_64.AppImage | cut -d' ' -f1)"
rmdir "${TMPDIR:-/tmp}"/.mount_dracae* 2>/dev/null
```

O primeiro comando apaga só o diretório desta versão, sem tocar em outros AppImages. O segundo remove apenas
diretórios **vazios**, então não mexe num ponto de montagem em uso. Com FUSE sobra só um diretório vazio
`.mount_dracae*`, que não se acumula.

## Como usar
Com uma atividade de **prática** carregada em uma aba do navegador que o Dracaena controla (por CDP):

```bash
./dracaena-x86_64.AppImage daemon      # inicia o servidor local (modo simulação: não clica na página)
./dracaena-x86_64.AppImage ask         # consulta só a questão atual e mostra a resposta, sem clicar
./dracaena-x86_64.AppImage once        # processa uma única questão e para
./dracaena-x86_64.AppImage status      # mostra o estado atual do daemon
```

**Só abas `http://` ou `https://` são lidas.** Páginas abertas como arquivo local (`file://`) são ignoradas, e o
Dracaena responde `Nenhuma questão visível nas abas abertas.` Para testar com um HTML local, sirva a pasta por um
servidor local e abra o endereço `http://`:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory <pasta-do-html>
# abra http://127.0.0.1:8765/<arquivo>.html no navegador do Dracaena
```

Essa mesma mensagem aparece quando a aba está em `http(s)` mas nenhuma questão é reconhecida na página.

## Compatibilidade

| Requisito | Detalhe |
| --- | --- |
| Arquitetura | Somente x86_64. Não há build ARM (aarch64). |
| glibc | **2.28 ou mais nova** (maior símbolo exigido em todos os 78 ELFs: `GLIBC_2.28`, medido com `objdump -T`; o build falha acima disso). |
| FUSE | **`libfuse2` não é mais necessária.** O modo FUSE precisa só de `/dev/fuse` e de `fusermount3` ou `fusermount` (pacote `fuse3`, presente na maioria dos desktops). Sem eles, use o modo de extração. |
| Bibliotecas do navegador | O Chromium embutido usa bibliotecas de desktop do sistema: NSS, GTK/ATK, GBM/DRM, X11/XCB, ALSA, CUPS, D-Bus, Pango/Cairo. Um desktop Linux comum já as tem. |
| Claude Code | `claude` precisa estar instalado e autenticado no PATH. O AppImage não o inclui. |

Distribuições que atendem a glibc 2.28, como referência: Ubuntu 20.04+, Debian 10+,
RHEL/Rocky/AlmaLinux 8+, Fedora 29+, Linux Mint 20+, Pop!_OS 20.04+, Zorin 16+,
Arch/Manjaro atuais, openSUSE Leap 15.3+ e Tumbleweed. Só as imagens da matriz foram medidas; as demais
são deduzidas da versão de glibc de cada distribuição.

Não suportados nesta release: distribuições com glibc mais antiga que a 2.28 (CentOS 7, Ubuntu 18.04),
Alpine e outras distribuições musl, ARM, macOS e Windows. Para essas plataformas é preciso um
build sobre uma base mais antiga ou um pacote próprio.

## Verificação feita

### Resultados da rc7 (valem para esta release)
Tag `v0.1.0-rc7`, commit `4740971`, run 44107651864 do workflow `AppImage`, todos os jobs verdes.
Artefato `dracaena-x86_64.AppImage`: 240.523.768 bytes,
SHA-256 `a820798a7d4d20d33e04e761e6d209556c4d89ed9acbe53e9317482432c26b1f`.
O build não é reprodutível bit a bit, então outro build do mesmo commit terá outro SHA-256.

- **glibc:** máximo `GLIBC_2.28` em 78 ELFs (`glibc-max.txt` do artefato); o build falha se algum exigir mais.
- **`verify.sh`:** resultado `OK` (`--version`, `--help`, `doctor` e daemon com socket e `status`, em contêiner sem Python do sistema).
- **`--version`:** `dracaena 0.1.0` no artefato baixado.
- **Matriz** (`matrix.sh`, 11 imagens limpas, sem instalar pacotes): as 10 imagens glibc passam em tudo,
  inclusive na coluna **FUSE (+fuse3)**, que instala só `fuse3` na imagem (sem `libfuse2`). A coluna
  **FUSE (limpa)** é N-T porque a imagem limpa não tem `fusermount` (`No suitable fusermount binary found on the $PATH`).
  Só o Alpine (musl) falha, como esperado, e o job fica verde nele. A coluna `navegador` confere, sem
  `BROWSER_BIN`, Firefox padrão, Chromium padrão e nenhum navegador (Firefox e nenhum usam o Chromium embutido).

| Distro | glibc | `--version` | `--help` | `doctor` | daemon + IPC | navegador | extract-and-run | FUSE (limpa) | FUSE (+fuse3) | Resultado |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Ubuntu 20.04 | 2.31 | OK | OK | OK | OK | OK | OK | N-T | OK | OK; FUSE (limpa) não testada: a imagem não tem `fusermount` |
| Ubuntu 22.04 | 2.35 | OK | OK | OK | OK | OK | OK | N-T | OK | OK; FUSE (limpa) não testada: a imagem não tem `fusermount` |
| Ubuntu 24.04 | 2.39 | OK | OK | OK | OK | OK | OK | N-T | OK | OK; FUSE (limpa) não testada: a imagem não tem `fusermount` |
| Debian 11 | 2.31 | OK | OK | OK | OK | OK | OK | N-T | OK | OK; FUSE (limpa) não testada: a imagem não tem `fusermount` |
| Debian 12 | 2.36 | OK | OK | OK | OK | OK | OK | N-T | OK | OK; FUSE (limpa) não testada: a imagem não tem `fusermount` |
| Fedora latest | 2.44 | OK | OK | OK | OK | OK | OK | N-T | OK | OK; FUSE (limpa) não testada: a imagem não tem `fusermount` |
| Arch Linux latest | 2.44 | OK | OK | OK | OK | OK | OK | N-T | OK | OK; FUSE (limpa) não testada: a imagem não tem `fusermount` |
| openSUSE Tumbleweed | 2.44 | OK | OK | OK | OK | OK | OK | N-T | OK | OK; FUSE (limpa) não testada: a imagem não tem `fusermount` |
| AlmaLinux 8 | 2.28 | OK | OK | OK | OK | OK | OK | N-T | OK | OK; FUSE (limpa) não testada: a imagem não tem `fusermount` |
| AlmaLinux 9 | 2.34 | OK | OK | OK | OK | OK | OK | N-T | OK | OK; FUSE (limpa) não testada: a imagem não tem `fusermount` |
| Alpine latest (não suportado) | musl 1.2.6 | FALHA | FALHA | FALHA | FALHA | FALHA | OK | N-T | FALHA | falha esperada: executável glibc não carrega em musl |

A matriz roda em contêineres Docker sobre o kernel do runner. Isso não substitui um teste em máquina real, e o
navegador foi verificado pela escolha do executável (`doctor` e `install-browser`), não por uma sessão de navegação.

### Teste em desktop real (Arch Linux, rc7)
Teste em máquina física com sessão gráfica, sobre o artefato da rc7 (mesmo SHA-256 acima), com glibc 2.44.
A sessão era Wayland, mas o Chromium foi forçado a X11 (`--ozone-platform=x11`) para obter uma janela funcional.
Configuração, dados, perfil e runtime ficaram em diretórios temporários; `BROWSER_BIN` vazio e a descoberta de
navegadores do sistema neutralizada.

- `--version` mostrou `dracaena 0.1.0`, e o `doctor` escolheu o **Chromium embutido**.
- O Chromium abriu uma página local de teste em janela visível, com o perfil dedicado do Dracaena.
- O CDP respondeu **somente em `127.0.0.1`** (porta efêmera); o `webSocketDebuggerUrl` também apontou para `127.0.0.1`.
- Os processos do Chromium **não receberam `--no-sandbox`**, e o teste não precisou de `DRACAENA_CHROMIUM_NO_SANDBOX`.
- O `daemon` iniciou em `DRY_RUN=true`, e `dracaena ask` chegou ao daemon.
- **Leitura da questão, verificada:** com a página de teste (`radio_rotulos.html`, grupo de rádio com rótulos externos)
  servida por HTTP em `127.0.0.1:8765` e aberta como `http://127.0.0.1:8765/radio_rotulos.html` no Chromium embutido,
  `ask` e `once` chegaram ao laço, o daemon registrou `aba escolhida (heuristic)` e `tipo da questão: SINGLE`.
- `stop` e SIGTERM encerraram daemon, Chromium e servidor local, sem processos nem socket residuais.
- **Falha encontrada na rc7 (corrigida depois dela):** depois de escolher a aba, `ask` e `once` pararam com
  `FileNotFoundError` para `prompts/answer.txt`: os textos de `prompts/` não estavam no pacote, e o `doctor` não
  detectava a ausência. A correção está em "Mudanças desde a rc7" (Task-021, #114).
- Uma primeira execução, com a página aberta de outro modo, terminou com `Nenhuma questão visível nas abas abertas.`
  (ver "Como usar": só abas `http://` e `https://` são lidas).

### Histórico das fases anteriores
As seções abaixo registram como o pacote chegou aqui. Os números de rc3 e rc4 (glibc 2.35, runtime AppImageKit 13)
estão superados pela tabela da rc7.

### Fase C: base glibc 2.28 (branch `feat/appimage-glibc-228`)

O build passou do Ubuntu 22.04 para a imagem `manylinux_2_28` (AlmaLinux 8) fixada por digest,
com `gcc-toolset-14` e `dnf` no lugar de `apt`. Artefato local: 240.527.864 bytes, SHA-256
`cf0fccd45348de6de483cb6a6b9a43ddfc890ddc636b131486cd16e725135b5c`.

**glibc medida** (`glibc-max.sh`, `objdump -T` com `readelf --version-info` de conferência,
em todos os ELFs do AppDir): **máximo GLIBC_2.28 em 78 ELFs; nenhum acima de 2.28.** Estão
exatamente em 2.28: `libpython3.12`, `libsqlite3`, `libuuid`, o `node` do driver e `fcntl`.
O Chromium (`chrome`) exige 2.25. Na rc6 eram 84 ELFs com máximo 2.35 (20 acima de 2.28).

| Medição (host Arch, SSD, `env` limpo) | rc6 (glibc 2.35) | Fase C (glibc 2.28) |
|---|---:|---:|
| Tamanho do arquivo | 241.691.128 bytes | 240.527.864 bytes (−0,5 %) |
| `--version` por FUSE (mediana de 10) | 0,15 s | 0,15 s |
| `--version` com extract-and-run (mediana de 5) | 1,47 s | 1,48 s |

`check-cases.py`: **16/16 OK**. Matriz (`matrix.sh`, 11 imagens): **Ubuntu 20.04, 22.04, 24.04,
Debian 11 e 12, Fedora, Arch, openSUSE Tumbleweed e AlmaLinux 8 e 9 passam em tudo**, inclusive
na coluna FUSE (+fuse3); o AlmaLinux 8 tem exatamente glibc 2.28, o piso. Só o Alpine (musl)
falha, como esperado. A coluna FUSE (limpa) segue N-T (imagem sem `fusermount`).

Regressões verificadas:

- **Certificados/HTTPS:** `--py-selftest-https` no pacote faz um GET real em `https://pypi.org/simple/`
  e devolve HTTP 200, com as CAs do host, em Ubuntu 20.04, 22.04 e 24.04, Debian 11 e 12, Fedora, Arch,
  openSUSE Tumbleweed e AlmaLinux 8 e 9 (a imagem `debian:11` pura não traz `ca-certificates` e
  só passou depois de instalá-lo, como em qualquer desktop). Sem o ajuste do `SSL_CERT_FILE`
  o Python compilado na AlmaLinux 8 procuraria `/etc/pki/tls`, que não existe fora da família RHEL.
- **ctypes/libffi, sqlite3, zlib/bz2/lzma, uuid, readline, curses:** OK nas mesmas 10 imagens.
- **Chromium embutido:** no primeiro build da base 2.28 o PyInstaller empacotou as bibliotecas de
  desktop da imagem (libglib 2.56, libX11, libgbm, libdbus...) e o `LD_LIBRARY_PATH` as impôs ao
  Chromium, que caía no Ubuntu 22.04 e no Debian 12 (`undefined symbol: g_memdup2` no libpango do
  host). Agora o Chromium fica fora da análise do PyInstaller, o pacote só leva as bibliotecas do
  Python e `entry.py` devolve o `LD_LIBRARY_PATH` original aos filhos. Verificado no Ubuntu 22.04
  com as bibliotecas de desktop instaladas: `doctor` abre o Chromium embutido por CDP com
  `LD_LIBRARY_PATH` vazio. O `chrome` direto, sem o `LD_LIBRARY_PATH` do PyInstaller, também abriu no Debian 12; o teste com
  `doctor` não foi repetido nele nem no Ubuntu 24.04 (que ainda tem a restrição de AppArmor).

Ressalvas: o Python embutido passa a usar OpenSSL 1.1.1k (AlmaLinux 8, corrigido pela Red Hat, mas fora do
suporte upstream); o app só usa HTTP local (CDP). O bootloader do PyInstaller continua o do wheel
(2.14, dentro do gate), sem recompilar do sdist. Zorin e máquinas físicas não foram testados.

### Fase B: runtime estático (branch `feat/appimage-runtime-estatico`)

O AppImage passa a usar o runtime oficial `AppImage/type2-runtime` release `20251108`
(SHA-256 `2fca8b44...ec260d`, estático, sem entradas `NEEDED`) e squashfs zstd, no lugar do
AppImageKit 13 com xz. O pacote abre por FUSE sem `libfuse2`. Artefato do build local:
241.695.224 bytes, SHA-256 `777cf649b4fbf9f4dfb5b30c8bd7558892ad6358d4f220aa7d74c2a66d00bd1e`.

| Medição (host Arch, SSD, `env` limpo) | rc4 (xz, AppImageKit 13) | Fase B (zstd, type2) |
|---|---:|---:|
| Tamanho do arquivo | 255.882.432 bytes | 241.695.224 bytes (−5,5 %) |
| `--version` por FUSE (mediana de 10) | 0,75 s | 0,15 s |
| `--version` com `--appimage-extract-and-run` (mediana de 5, `TMPDIR` novo) | 23,2 s | 1,48 s |
| Idem, segunda execução no mesmo `TMPDIR` | 23,2 s | 0,53 s |
| Resíduo em `TMPDIR` após extract-and-run | 0 | ~600 MB (`appimage_extracted_<md5>`) |
| Resíduo em `TMPDIR` após FUSE | 0 | 1 diretório vazio `.mount_*` |

O que o runtime ainda exige do host: `/dev/fuse` e `fusermount3` ou `fusermount` no PATH
(sem eles: `No suitable fusermount binary found on the $PATH`). `check-cases.py`: **16/16 OK**.
Matriz (`matrix.sh`, 11 imagens): as 6 suportadas (Ubuntu 22.04 e 24.04, Debian 12, Fedora,
Arch, openSUSE Tumbleweed) passam em tudo, inclusive na nova coluna **FUSE (+fuse3)**, que
instala só `fuse3` na imagem (sem `libfuse2`) e roda o AppImage por FUSE. A coluna **FUSE
(limpa)** continua N-T nelas, porque a imagem limpa não tem `fusermount`. As cinco não suportadas (nessa fase,
base glibc 2.35: glibc < 2.35 ou musl) falhavam como esperado; a fase C abaixou o piso para 2.28. Não testado: Zorin 17/18 reais e máquinas físicas.

#### Resultados da fase anterior (rc3/rc4, runtime AppImageKit 13)
Resultados da rc3 (tag `v0.1.0-rc3`, commit `e553cc8`, run 44076261704 do workflow
`AppImage`). Artefato `dracaena-x86_64.AppImage`, 255.882.432 bytes,
SHA-256 `b4e4cc9aacec0e19fb36084212a268d7b8341528838542a12b80261762f27d3f`.

Na rc4 (tag `v0.1.0-rc4`, commit `1fa121e`, run 44078391109) o workflow inteiro ficou
verde. Ela só muda o CI e a matriz, que agora separa as distribuições não suportadas
(falha esperada) das regressões. O código empacotado é o mesmo da rc3. Como o build
não é reprodutível bit a bit, o artefato da rc4 tem outro SHA-256.

O job `appimage` passou em `verify.sh` (resultado `OK`): `--version`, `--help`, `doctor`
e `daemon` com socket e `status` respondendo, em contêiner sem Python do sistema. O job
`compatibilidade` roda `packaging/appimage/matrix.sh` em 11 imagens limpas, sem instalar
pacotes. A coluna `navegador` confere, sem `BROWSER_BIN`, Firefox padrão, Chromium padrão
e nenhum navegador (Firefox e nenhum usam o Chromium embutido).

| Distro | libc | `--version` | `--help` | `doctor` | daemon + IPC | navegador | extract-and-run | FUSE | Resultado |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Ubuntu 20.04 (não suportado) | 2.31 | FALHA | FALHA | FALHA | FALHA | FALHA | OK | N-T | falha esperada: `GLIBC_2.35` não encontrada |
| Ubuntu 22.04 | 2.35 | OK | OK | OK | OK | OK | OK | N-T | OK; FUSE não testado (imagem sem `libfuse2`) |
| Ubuntu 24.04 | 2.39 | OK | OK | OK | OK | OK | OK | N-T | OK; FUSE não testado (imagem sem `libfuse2`) |
| Debian 11 (não suportado) | 2.31 | FALHA | FALHA | FALHA | FALHA | FALHA | OK | N-T | falha esperada: `GLIBC_2.35` não encontrada |
| Debian 12 | 2.36 | OK | OK | OK | OK | OK | OK | N-T | OK; FUSE não testado (imagem sem `libfuse2`) |
| Fedora latest | 2.44 | OK | OK | OK | OK | OK | OK | N-T | OK; FUSE não testado (imagem sem `libfuse2`) |
| Arch Linux latest | 2.44 | OK | OK | OK | OK | OK | OK | N-T | OK; FUSE não testado (imagem sem `libfuse2`) |
| openSUSE Tumbleweed | 2.44 | OK | OK | OK | OK | OK | OK | N-T | OK; FUSE não testado (imagem sem `libfuse2`) |
| AlmaLinux 8 (não suportado) | 2.28 | FALHA | FALHA | FALHA | FALHA | FALHA | OK | N-T | falha esperada: `GLIBC_2.35` não encontrada |
| AlmaLinux 9 (não suportado) | 2.34 | FALHA | FALHA | FALHA | FALHA | FALHA | OK | N-T | falha esperada: `GLIBC_2.35` não encontrada |
| Alpine latest (não suportado) | musl 1.2.6 | FALHA | FALHA | FALHA | FALHA | FALHA | FALHA | FALHA | falha esperada: executável glibc não carrega em musl |

- **OK** em Ubuntu 22.04 e 24.04, Debian 12, Fedora, Arch e openSUSE Tumbleweed (glibc 2.35 ou mais nova).
- **FUSE não testado** nessas imagens, porque elas não trazem `libfuse2` (`dlopen(): error loading libfuse.so.2`). Isso conta como "não testado", não como falha. A extração do AppImage funcionou em todas as imagens glibc; nas não suportadas só a execução falha.
- **Falha esperada** em Ubuntu 20.04, Debian 11, AlmaLinux 8 e AlmaLinux 9 (glibc 2.31, 2.31, 2.28 e 2.34): o Python embutido exige `GLIBC_2.35`. O Alpine (musl) também falha, como previsto.
- O job fica verde nas distribuições não suportadas e vermelho só se uma suportada regredir.
- `doctor` sai com 1 quando faltam dependências externas, como o Claude Code. Isso é esperado nas imagens limpas.

A matriz roda dentro de contêineres Docker sobre o kernel do runner. Isso não substitui um
teste em máquina real, e o navegador foi verificado pela escolha do executável (`doctor` e
`install-browser`), não por uma sessão de navegação.

### Escolha do navegador

O Dracaena escolhe o navegador nesta ordem:

1. `BROWSER_BIN` informado nas configurações. Se não for um Chromium válido, o
   Dracaena para com erro e não troca de navegador sozinho.
2. O navegador padrão do sistema, quando é Chromium (Chrome, Chromium, Edge, Brave,
   Vivaldi, Opera ou outro que responda ao CDP).
3. O Chromium embutido no AppImage, quando não há navegador configurado e o padrão
   detectado não serve (por exemplo, Firefox) ou não existe nenhum. Não há download:
   o Chromium já vem no pacote, e `BROWSER_FALLBACK=playwright` (padrão) o mantém ativo.

Com o padrão incompatível, `doctor` e `install-browser` informam que o Chromium
embutido será usado em vez de acusar erro. O job `compatibilidade` do CI confere os
três cenários (Firefox padrão, Chromium padrão e nenhum navegador) em cada imagem.

### Sandbox do Chromium embutido no Ubuntu 24.04

O Ubuntu 24.04 restringe, por AppArmor, a criação de user namespaces por programas sem
perfil (`kernel.apparmor_restrict_unprivileged_userns`). O Chromium embutido depende
deles para o sandbox e pode não iniciar. O Dracaena nunca desliga o sandbox por conta
própria. Quando o Chromium embutido encerra com erro de sandbox, o erro explica a causa
e as opções:

- criar um perfil AppArmor que permita `userns` para o executável do Chromium embutido;
- ou ajustar o `sysctl` `kernel.apparmor_restrict_unprivileged_userns`;
- ou, como último recurso, aceitar o risco com `DRACAENA_CHROMIUM_NO_SANDBOX=1`.

`DRACAENA_CHROMIUM_NO_SANDBOX=1` inicia o Chromium embutido com `--no-sandbox` e
registra um aviso no log. Vale só para o Chromium embutido: um navegador do sistema ou
o informado em `BROWSER_BIN` nunca recebe `--no-sandbox`. Sem esse sandbox, uma página
maliciosa tem menos barreiras contra o sistema; use só em máquinas e sites de confiança.

Ainda não verificado:
- Ubuntu 24.04 desktop com a restrição de AppArmor a user namespaces ativa (o comportamento do sandbox do
  Chromium embutido ali).
- Firefox como navegador padrão em uma instalação real (a matriz só simula o padrão com stubs).
- Uma sessão Wayland sem forçar X11.
- O clique de verdade: a simulação (`DRY_RUN=true`) foi verificada até `(dry-run) faria: ...`, mas o clique real,
  com o `DRY_RUN` desligado, não foi testado. A confirmação da correção dos prompts **sobre o artefato da tag da
  rc8** vem do `verify.sh` do CI (item `prompts empacotados`); até lá ela só foi verificada em build local.
- Zorin e outras máquinas físicas além do Arch testado. A matriz roda em contêineres: o glibc 2.28 foi medido
  no AlmaLinux 8, que tem exatamente esse piso.
Os testes da branch servem para isso.

## Mudanças desde a rc7
- **Prompts no pacote (Task-021, #114).** Na rc7 o AppImage não trazia `prompts/*.txt`, e `ask` e `once` paravam com
  `FileNotFoundError`. Agora o `dracaena.spec` empacota os quatro arquivos (`system.txt`, `answer.txt`, `invalid.txt`,
  `retry.txt`) em `_internal/prompts`, e o `entry.py` aponta `DRACAENA_PROMPTS` para essa pasta no executável
  congelado. O `doctor` passou a conferir o mesmo caminho que o núcleo lê (antes procurava um pacote que não existe e
  nunca acusava a falta), e o `verify.sh` ganhou o item `prompts empacotados`, que falha se faltar algum.
  **Verificado em build local** (240.527.864 bytes, SHA-256 `9e21e37d3e78e1af7854efeed36ae591cf98d9092acc5e9b83bde733933dcd35`,
  não é o artefato da rc8): suíte com 388 testes OK, `verify.sh` com `RESULTADO: OK` e 15 itens (o mesmo `verify.sh`
  sobre o AppImage da rc7 falha em `prompts empacotados`), `doctor` com `prompts: OK`, e `once` com `DRY_RUN=true` e
  a página de teste servida por HTTP chegando a `(dry-run) faria: [0] ...` sem `FileNotFoundError`.
- **Encerramento do IPC (Task-018, #91).** Corrida em `Listener.close()`: a thread do teste e o `finally` de
  `Daemon.serve()` chamavam `close()` ao mesmo tempo, e a segunda encontrava o socket já `None`. Agora `close()` roda sob
  um `threading.Lock` (idempotente) e `accept()` usa uma referência local do socket e levanta `OSError` se o servidor já
  fechou. Medido: 0 falhas em 300 repetições do teste sob carga (antes, 36 em 300) e 5 rodadas completas da suíte, todas OK.

## Decisões da 0.1.0: OpenSSL e resíduo de extração
- **OpenSSL.** O Python embutido usa OpenSSL 1.1.1k, da AlmaLinux 8 (corrigido pela Red Hat, mas fora do suporte
  upstream). O Dracaena só faz HTTP local (CDP, `127.0.0.1`) pelo Python; o Chromium usa BoringSSL próprio e o
  driver do Playwright traz o OpenSSL dele. Por isso a versão não afeta o uso normal, e **a release mantém a 1.1.1k**.
  Medido na rc7: as bibliotecas da 1.1.1k somam cerca de 4,6 MB dos 604 MiB descomprimidos. Compilar OpenSSL 3 no
  build é viável (cerca de 70 s a mais e cerca de 11 MB a mais), mas exigiria reverificar tudo. **Gatilho de revisão:** se um
  recurso futuro (atualização automática, telemetria, download) usar HTTPS pelo Python, o build deve migrar para
  OpenSSL 3 antes de ele entrar.
- **Resíduo em `TMPDIR`.** Fica só **documentado** (seção "Instalação"), sem limpeza automática. O `AppRun` termina
  com `exec`, e limpar ao sair o transformaria em processo pai (muda PID e sinais do daemon de longa duração). O
  diretório extraído também é reaproveitado entre execuções, e apagá-lo ao sair de uma instância poderia afetar outra.

## Build e CI

- Local, com Docker: `packaging/appimage/build.sh` (saída em `dist/appimage/`).
- GitHub Actions: o workflow `.github/workflows/appimage.yml` roda em tag `v*` ou
  por disparo manual (`workflow_dispatch`). Ele faz o build no contêiner
  `quay.io/pypa/manylinux_2_28_x86_64` (AlmaLinux 8, glibc 2.28) fixado por digest, roda
  `verify.sh` num contêiner `ubuntu:22.04` sem o Python do sistema e publica o AppImage
  como artefato do workflow por 14 dias. O workflow não roda em `pull_request`.
- Job `compatibilidade`: roda `packaging/appimage/matrix.sh` em 11 imagens limpas (Ubuntu
  20.04/22.04/24.04, Debian 11/12, Fedora, Arch, openSUSE Tumbleweed, AlmaLinux 8/9 e
  Alpine), sem instalar pacotes, e publica uma linha da matriz por imagem. O Alpine
  (musl) é marcado como "não suportado, falha esperada": a falha não reprova o job, que só fica
  vermelho se uma imagem suportada regredir.

Detalhes técnicos do empacotamento estão em [`README.md`](README.md).

## Como testar e reportar

1. Baixe o AppImage do artefato do workflow ou da pré-release.
2. Rode `--version`, `doctor` e `daemon` no seu sistema.
3. Anote a distribuição e a versão, a saída de `ldd --version | head -1`, se usou FUSE ou
   extração e o erro completo, se houver.
