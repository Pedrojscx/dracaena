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

Não suportados nesta release: Ubuntu 20.04, Debian 11, RHEL/Rocky/Alma 8 e outras
distribuições com glibc mais antiga, além de ARM, macOS e Windows.
Para essas plataformas é preciso um build sobre uma base mais antiga ou um pacote próprio.

## Verificação feita

No artefato `dracaena-x86_64.AppImage` (255.878.336 bytes,
SHA-256 `f86105bb906de56347016d63bfa707323579b2577f8ee88b53796c9276842f4e`):

```bash
python3 -I packaging/appimage/check-cases.py dracaena-x86_64.AppImage
```

Resultado: **16/16 casos OK**. Foram executados `--help`, `--version`, `doctor` e
`install-browser` com `env -i`, em FUSE e em extração, direto e por link simbólico.
Não sobrou diretório em `TMPDIR`.

`doctor` sai com 1 quando faltam dependências externas, como o Claude Code. Isso
é esperado no ambiente limpo do teste.

Observação: neste host, `install-browser` responde `{"ok": false, ...}` porque o
navegador padrão detectado não é Chromium e não responde ao CDP. A resposta é
coerente com a regra de navegador configurado ou detectado primeiro, mas ainda
falta confirmar se o Chromium embutido é usado como fallback nesse caso.

Ainda não verificado: sessão real de navegador com o Chromium embutido em outras
distribuições, o daemon real respondendo a uma atividade de verdade e execução em
glibc exatamente 2.35 fora do contêiner de build. Os testes da branch servem para isso.

## Build e CI

- Local, com Docker: `packaging/appimage/build.sh` (saída em `dist/appimage/`).
- GitHub Actions: o workflow `.github/workflows/appimage.yml` roda em tag `v*` ou
  por disparo manual (`workflow_dispatch`). Ele faz o build no contêiner `ubuntu:22.04`
  fixado por digest, roda `verify.sh` sem o Python do sistema e publica o AppImage
  como artefato do workflow por 14 dias.

Detalhes técnicos do empacotamento estão em [`README.md`](README.md).

## Como testar e reportar

1. Baixe o AppImage do artefato do workflow ou da pré-release.
2. Rode `--version`, `doctor` e `daemon` no seu sistema.
3. Anote a distribuição e a versão, a saída de `ldd --version | head -1`, se usou FUSE ou
   extração e o erro completo, se houver.
