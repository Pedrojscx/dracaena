# AppImage CLI x86_64 — fase 1

No host com Docker: `packaging/appimage/build.sh`.
Dentro de ubuntu:22.04, como root: `bash packaging/appimage/container-build.sh`.
`OUT_DIR` tem padrão `dist/appimage`. No host deve ser relativo à raiz do
repositório; dentro do container também aceita caminho absoluto. A última linha
contém o caminho do artefato. O wrapper monta o código somente para leitura e
apenas a pasta de saída para escrita. O container instala os pacotes de build
pelos repositórios autenticados da distribuição, compila Python 3.12.8 e congela
o entry point `dracaena.cli:main`, sem alterar a aplicação.

Python e appimagetool têm SHA-256 fixado; PyInstaller e suas dependências têm
versão e SHA-256 fixados em `requirements-build.txt`, inclusive transitivas.
O pip exige hashes e aceita somente wheels. O runtime AppImageKit 13 também tem hash
fixo, o que impede o download implícito de um runtime variável pelo appimagetool. Fontes: python.org,
pypi.org e releases oficiais AppImage. Os pacotes do sistema e a imagem
ubuntu:22.04 recebem atualizações; o `apt-get` não é fixado por versão ou snapshot.
Este build não promete identidade bit a bit.

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
No modo FUSE o runtime precisa de `fusermount` no PATH; sem ele, use
`APPIMAGE_EXTRACT_AND_RUN=1`.

Playwright 1.64.1, seu driver e dependências entram no pacote, com versões e
SHA-256 fixados. O squashfs usa compressão xz. Como o compressor embutido no empacotador
só aceita zstd, o build extrai a ferramenta verificada e substitui seu
`mksquashfs` pelo pacote autenticado `squashfs-tools` da distribuição. O Chromium
reserva (Chrome for Testing 156.0.8078.4, revisão 1248, SHA-256 fixado) é embutido
somente leitura em `_internal/dracaena-browsers`. `entry.py` aponta o fallback do
Playwright para essa cópia, no lugar do download para a pasta de dados do usuário.
O Chromium ainda usa as bibliotecas de desktop do sistema (NSS, GTK/ATK, GBM, X11, ALSA).
Não entram Qt ou bandeja. `doctor` pode retornar 1 por dependências externas
ausentes. Recursos JSON/TXT do pacote entram como dados. O projeto não é
instalado via pip: o build seleciona suas dependências explicitamente.

Saídas adicionais: `bundled-sizes.txt` (bytes por arquivo, maior primeiro) e
`build-packages.txt` (versões do ambiente de congelamento).

Verificação independente pertence a `verify.sh`, entregue separadamente.
Para rodar sem FUSE, use `APPIMAGE_EXTRACT_AND_RUN=1`.
No modo `--appimage-extract-and-run` o runtime extrai o pacote para um diretório
temporário, que respeita `TMPDIR`. Na medição do runtime 13 (`--version`) nenhum
`appimage_extracted_*` ficou em `TMPDIR` após a saída; esse comportamento não é
garantido pelo formato e o `check-cases.py` o registra apenas como informação.
Na branch `release/appimage-v0.1.0`, `--help` lista os dez subcomandos, `--version`
está disponível e o daemon real está incluído (modo simulação por padrão, via
`DRY_RUN`). Notas da release: [`RELEASE.md`](RELEASE.md).

## Requisitos e resíduos

- **glibc 2.35 ou mais nova** (Linux x86_64). O build roda em ubuntu:22.04 e o maior
  símbolo exigido pelos binários do pacote é `GLIBC_2.35` (medido com `objdump -T`).
  Distribuições com glibc mais velha não são suportadas.
- **Sem FUSE:** `--appimage-extract-and-run` (ou `APPIMAGE_EXTRACT_AND_RUN=1`) extrai o
  pacote em um diretório temporário sob `TMPDIR` (padrão `/tmp`). O pacote com driver ocupa mais espaço que os 51 MiB da versão anterior. Veja a seção de extração acima sobre resíduos.
- **python-xlib** (atalho global X11) fica fora do AppImage da fase 1. Ele vem de
  `requirements.txt` só para a UI. O build usa `requirements-build.txt`, que não o lista,
  e o pacote não tem arquivos `xlib`.

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

## Runtime xz

O runtime de 20251108 não lê squashfs com xz. Este build usa o runtime oficial
AppImageKit 13, com SHA-256 fixo. O modo FUSE precisa de libfuse2 no Ubuntu 22.04
ou libfuse2t64 no Ubuntu 24.04. Sem FUSE, use `--appimage-extract-and-run`.
O runtime é mais antigo; as verificações no Ubuntu cobrem extração e o daemon
simulado. Elas não provam que o daemon real nem uma sessão de navegador funcionam.
