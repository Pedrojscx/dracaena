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
| Runtime AppImage | AppImageKit 13, squashfs xz |

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

Sem FUSE (contêineres, WSL, algumas distribuições mínimas):

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./dracaena-x86_64.AppImage --version
# ou
./dracaena-x86_64.AppImage --appimage-extract-and-run --version
```

## Compatibilidade

| Requisito | Detalhe |
| --- | --- |
| Arquitetura | Somente x86_64. Não há build ARM (aarch64). |
| glibc | 2.35 ou mais nova (maior símbolo exigido: `GLIBC_2.35`, medido com `objdump -T`). |
| FUSE | `libfuse2` (Ubuntu 22.04) ou `libfuse2t64` (Ubuntu 24.04). Sem FUSE, use o modo de extração. |
| Bibliotecas do navegador | O Chromium embutido usa bibliotecas de desktop do sistema: NSS, GTK/ATK, GBM/DRM, X11/XCB, ALSA, CUPS, D-Bus, Pango/Cairo. Um desktop Linux comum já as tem. |
| Claude Code | `claude` precisa estar instalado e autenticado no PATH. O AppImage não o inclui. |

Distribuições que atendem a glibc 2.35, como referência: Ubuntu 22.04+, Debian 12+,
Fedora 36+, Linux Mint 21+, Pop!_OS 22.04+, Arch/Manjaro atuais, openSUSE Tumbleweed.

Não suportados nesta release: Ubuntu 20.04 (glibc 2.31), Debian 11 (2.31),
RHEL/Rocky/AlmaLinux 8 (2.28) e 9 (2.34, medido no AlmaLinux 9) e outras distribuições com glibc
mais antiga que a 2.35, além de Alpine e outras distribuições musl, ARM, macOS e Windows.
Para essas plataformas é preciso um build sobre uma base mais antiga ou um pacote próprio.

## Verificação feita
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
