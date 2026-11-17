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

Sem FUSE (contêineres, WSL, algumas distribuições mínimas) o AppImage também roda por extração.
Ela grava cerca de 600 MB em `TMPDIR` e **não os apaga ao sair** (o runtime novo não faz a limpeza);
o diretório `appimage_extracted_<hash>` é reaproveitado nas execuções seguintes e pode ser removido à mão:

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./dracaena-x86_64.AppImage --version
# ou
./dracaena-x86_64.AppImage --appimage-extract-and-run --version
```

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
(limpa)** continua N-T nelas, porque a imagem limpa não tem `fusermount`. As cinco não suportadas
falham como esperado (glibc < 2.35 ou musl). Não testado: Zorin 17/18 reais e máquinas físicas.

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

Ainda não verificado: sessão real de navegador com o Chromium embutido em outras
distribuições, o daemon real respondendo a uma atividade de verdade e execução em
glibc exatamente 2.35 fora do contêiner de build. Também falta confirmar o
comportamento do sandbox em um Ubuntu 24.04 real, com a restrição de AppArmor ativa.
Os testes da branch servem para isso.

## Build e CI

- Local, com Docker: `packaging/appimage/build.sh` (saída em `dist/appimage/`).
- GitHub Actions: o workflow `.github/workflows/appimage.yml` roda em tag `v*` ou
  por disparo manual (`workflow_dispatch`). Ele faz o build no contêiner `ubuntu:22.04`
  fixado por digest, roda `verify.sh` sem o Python do sistema e publica o AppImage
  como artefato do workflow por 14 dias.
- Job `compatibilidade`: roda `packaging/appimage/matrix.sh` em 11 imagens limpas (Ubuntu
  20.04/22.04/24.04, Debian 11/12, Fedora, Arch, openSUSE Tumbleweed, AlmaLinux 8/9 e
  Alpine), sem instalar pacotes, e publica uma linha da matriz por imagem. As imagens com
  glibc anterior à 2.35 e o Alpine (musl) são marcadas como "não suportado, falha esperada":
  a falha não reprova o job, que só fica vermelho se uma imagem suportada regredir.

Detalhes técnicos do empacotamento estão em [`README.md`](README.md).

## Como testar e reportar

1. Baixe o AppImage do artefato do workflow ou da pré-release.
2. Rode `--version`, `doctor` e `daemon` no seu sistema.
3. Anote a distribuição e a versão, a saída de `ldd --version | head -1`, se usou FUSE ou
   extração e o erro completo, se houver.
