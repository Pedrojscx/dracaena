# AppImage CLI x86_64 — fase 1 (base glibc 2.28)

No host com Docker: `packaging/appimage/build.sh`.
Dentro de `quay.io/pypa/manylinux_2_28_x86_64` (AlmaLinux 8, glibc 2.28), como root:
`bash packaging/appimage/container-build.sh`. A imagem é fixada por digest em `build.sh` e em
`.github/workflows/appimage.yml`: `sha256:d086f64cddcace250ef0f0073583c51b8298159303290a730c9f59bd91edfd2c`
(criada em 2026-11-14).
`OUT_DIR` tem padrão `dist/appimage`. No host deve ser relativo à raiz do
repositório; dentro do container também aceita caminho absoluto. A última linha
contém o caminho do artefato. O wrapper monta o código somente para leitura e
apenas a pasta de saída para escrita. O container instala os pacotes `-devel`
com `dnf` (repositórios AlmaLinux 8, assinatura GPG conferida), compila Python 3.12.8 e congela
o entry point `dracaena.cli:main`, sem alterar a aplicação.

Python e appimagetool têm SHA-256 fixado; PyInstaller e suas dependências têm
versão e SHA-256 fixados em `requirements-build.txt`, inclusive transitivas.
O pip exige hashes e aceita somente wheels. O runtime estático type2 `20251108` também tem
hash fixo (ver "Runtime estático"), o que impede o download implícito de um runtime variável
pelo appimagetool. Fontes: python.org, pypi.org e releases oficiais AppImage. Este build não promete identidade bit a bit.

O que deixa de ser "pacote autenticado da distribuição": a base de build não é mais a imagem
oficial do Ubuntu, e sim a `manylinux_2_28` da PyPA, de terceiros, confiada pelo digest (um digest
novo exige revisão). Dela vêm o compilador (`gcc-toolset-14`), `zlib-devel`, `file`, `unzip` e `curl`,
sem verificação de assinatura na hora do build. Só os pacotes que o `dnf` instala no build
(`openssl-devel`, `libffi-devel`, `sqlite-devel` etc.) são autenticados pelo repositório AlmaLinux,
sem fixar versão. O Python embutido usa o OpenSSL 1.1.1k da AlmaLinux 8 (corrigido pela Red Hat,
mas fora do suporte upstream), no lugar do OpenSSL 3 do Ubuntu 22.04.

`AppRun` usa como raiz o `$APPDIR` exportado pelo runtime (ponto de montagem
ou diretório extraído), o que cobre a invocação do AppImage por link simbólico;
só quando `$APPDIR` não existe a raiz vem de `$0`. Se a raiz não contém
`usr/bin/dracaena`, sai com 127 e mensagem. Ele preserva o `$APPIMAGE` original
absoluto e reexporta `$APPDIR` normalizado, para o launcher usar o arquivo
estável. A execução direta de um AppDir extraído não cria uma variável APPIMAGE
artificial. O launcher usa apenas builtins do shell: funciona com PATH vazio.
Diretórios relativos e links simbólicos nos diretórios são resolvidos por
`cd -P`/`pwd -P`. Sem runtime e sem `$APPDIR`, um link simbólico avulso para o
AppRun fora do AppDir não é resolvido (não há `readlink`); defina `APPDIR`.
No modo FUSE o runtime precisa de `fusermount3` ou `fusermount` no PATH e de `/dev/fuse`;
sem eles, use `APPIMAGE_EXTRACT_AND_RUN=1`. Não é preciso `libfuse2`.

Playwright 1.64.1, seu driver e dependências entram no pacote, com versões e
SHA-256 fixados. O squashfs usa compressão zstd, a única que o runtime estático lê, com o
`mksquashfs` que já vem no appimagetool 1.9.1 (SHA-256 fixo); o build não substitui
mais o compressor. O Chromium
reserva (Chrome for Testing 156.0.8078.4, revisão 1248, SHA-256 fixado) é embutido
somente leitura em `_internal/dracaena-browsers`. `entry.py` aponta o fallback do
Playwright para essa cópia, no lugar do download para a pasta de dados do usuário.
O Chromium é copiado para o AppDir depois do congelamento, fora da análise do PyInstaller, que
empacotaria as bibliotecas de desktop da imagem de build (glib, X11, gbm) e as imporia ao
navegador. Ele usa as bibliotecas de desktop do sistema (NSS, GTK/ATK, GBM, X11, ALSA), e
`entry.py` devolve aos processos filhos o `LD_LIBRARY_PATH` original.
Não entram Qt ou bandeja. `doctor` pode retornar 1 por dependências externas
ausentes. Recursos JSON/TXT do pacote entram como dados. O projeto não é
instalado via pip: o build seleciona suas dependências explicitamente.

Saídas adicionais: `bundled-sizes.txt` (bytes por arquivo, maior primeiro) e
`build-packages.txt` (versões do ambiente de congelamento).

Verificação independente pertence a `verify.sh`, entregue separadamente.
Para rodar sem FUSE, use `APPIMAGE_EXTRACT_AND_RUN=1`.
No modo `--appimage-extract-and-run` o runtime extrai o pacote (cerca de 600 MB) para
`$TMPDIR/appimage_extracted_<md5 do arquivo>` e **não o apaga ao sair** (medido com
strace: `wait4` e `exit_group`, sem `unlink`; o AppImageKit 13 apagava). O nome do diretório
depende do conteúdo do arquivo, então execuções seguintes com o mesmo `TMPDIR` o reutilizam
(`--version` cai de ~1,5 s para ~0,5 s), mas cada versão nova do AppImage deixa outro
diretório. No modo FUSE sobra só um diretório vazio `.mount_*` em `TMPDIR`. O `check-cases.py`
apaga o `TMPDIR` de cada caso para não encher o `/tmp`. Na branch
`release/appimage-v0.1.0`, `--help` lista os dez subcomandos, `--version`
está disponível e o daemon real está incluído (modo simulação por padrão, via
`DRY_RUN`). Notas da release: [`RELEASE.md`](RELEASE.md).

## Requisitos e resíduos

- **glibc 2.28 ou mais nova** (Linux x86_64). O build roda em AlmaLinux 8 (glibc 2.28) e o
  maior símbolo exigido por qualquer ELF do pacote é `GLIBC_2.28` (`glibc-max.sh`, `objdump -T`).
  O build falha se um ELF passar disso, e `glibc-max.txt` lista todos. O piso de 2.28 vem do
  Node do driver do Playwright e do `libpython`. Distribuições com glibc mais velha (por exemplo
  CentOS 7, Ubuntu 18.04) e musl (Alpine) não são suportadas.
- **FUSE:** o runtime é estático e não liga `libfuse.so.2`. O modo FUSE precisa só de
  `/dev/fuse` e de `fusermount3` ou `fusermount` (pacote `fuse3`, já presente na maioria dos
  desktops). Em Ubuntu 22.04+ o modo FUSE dispensa `libfuse2` (medido em contêiner; o Zorin 17/18, base Ubuntu, não foi testado).
- **Sem FUSE:** `--appimage-extract-and-run` (ou `APPIMAGE_EXTRACT_AND_RUN=1`) extrai o
  pacote (~600 MB) em `TMPDIR` (padrão `/tmp`) e o deixa lá. Veja a seção de extração acima.
- **python-xlib** (atalho global X11) fica fora do AppImage da fase 1. Ele vem de
  `requirements.txt` só para a UI. O build usa `requirements-build.txt`, que não o lista,
  e o pacote não tem arquivos `xlib`.

## Python embutido e certificados

`entry.py --py-selftest` (e `--py-selftest-https`, com rede) exercita o Python congelado:
ctypes/libffi (callback via `qsort`), ssl (CAs carregadas), sqlite3, zlib/bz2/lzma, uuid.
O Python é compilado com `OPENSSLDIR=/etc/pki/tls` (AlmaLinux 8); fora da família RHEL esse
caminho não existe, então `entry.py` aponta `SSL_CERT_FILE` para o primeiro pacote de CAs legível
entre `/etc/ssl/certs/ca-certificates.crt`, `/etc/pki/tls/certs/ca-bundle.crt`,
`/etc/ssl/ca-bundle.pem`, `/etc/pki/tls/cert.pem` e `/etc/ssl/cert.pem`. `SSL_CERT_FILE` e
`SSL_CERT_DIR` definidos pelo usuário têm prioridade.

## Verificação dos 16 casos

Da raiz do repositório, depois do build:

    python3 -I packaging/appimage/check-cases.py [arquivo.AppImage]

O script roda `--help`, `--version`, `doctor` e `install-browser` com `env -i`, em FUSE e em
`--appimage-extract-and-run`, direto e por link simbólico. Ele imprime o HEAD e o
SHA-256 do artefato verificado e sai com 0 só se os 16 casos passarem.

O caso `install-browser` roda sem entrada e sem `--yes`: deve devolver JSON de
confirmação pendente, provando que o driver inicializou sem baixar o navegador.
O download e a abertura do Chromium exigem um teste separado com as bibliotecas
de desktop instaladas. Incluir o driver não inclui essas bibliotecas do sistema.

## Runtime estático

Fonte: [`AppImage/type2-runtime`](https://github.com/AppImage/type2-runtime), release fixa
`20251108` (commit `dd6cebe`, nunca `continuous`), arquivo `runtime-x86_64`,
SHA-256 `2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d`
(a release também publica a assinatura `runtime-x86_64.sig`, chave
`570C 77AC EA40 C0F1 B758  902C BF96 CCA5 6490 F695`). O binário é static-pie sem
entradas `NEEDED` (`objdump -p`), carrega o FUSE embutido e não usa `libfuse.so.2`.
Do host ele ainda exige `/dev/fuse` e `fusermount3` ou `fusermount` no PATH; sem eles
sai com `No suitable fusermount binary found on the $PATH`. A compressão usada é zstd; o xz
não é lido, segundo o registro da fase anterior (não retestado aqui). O empacotador é o
appimagetool 1.9.1 (SHA-256 `ed4ce84f...384eb0`), cujo `mksquashfs` só gera zstd.
O appimagetool regrava seções do runtime, então o SHA-256 do trecho embutido no AppImage
difere do arquivo baixado.
