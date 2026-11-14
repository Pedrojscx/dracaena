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
O pip exige hashes e aceita somente wheels. O runtime 20251108 também tem hash fixado, evitando o
download implícito de um runtime variável pelo appimagetool. Fontes: python.org,
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

Playwright é importado apenas no fallback do navegador e fica excluído (zero
bytes do driver). Não entram navegador, Qt ou bandeja. `doctor` trata a ausência
do fallback como diagnóstico; pode retornar 1 por dependências externas ausentes.
Dependências locais incluídas: platformdirs e psutil. Recursos JSON/TXT existentes
no pacote entram como dados. Não se instala o projeto via pip para evitar baixar
as dependências gráficas/de navegador fora do escopo.

Saídas adicionais: `bundled-sizes.txt` (bytes por arquivo, maior primeiro) e
`build-packages.txt` (versões do ambiente de congelamento).

Verificação independente pertence a `verify.sh`, entregue separadamente.
Para rodar sem FUSE, use `APPIMAGE_EXTRACT_AND_RUN=1`.
O runtime deixa `/tmp/appimage_extracted_<hash>` após
`--appimage-extract-and-run` (aproximadamente 51 MiB por extração). Ele respeita
`TMPDIR`: defina-o para direcionar esse diretório a outro local. O diretório
persiste após a saída; considere esse consumo ao usar o modo sem FUSE.
Com a base 5844b3a, `--help` lista os dez subcomandos e `--version` está
disponível. O daemon real permanece indisponível; use `--simulate` para prática.
