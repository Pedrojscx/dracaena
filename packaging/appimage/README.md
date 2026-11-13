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

`AppRun` preserva o `$APPIMAGE` original absoluto e define `$APPDIR` para o
diretório do pacote. Isso permite ao launcher usar o arquivo estável. A execução
direta de um AppDir extraído não cria uma variável APPIMAGE artificial.
O launcher usa apenas builtins do shell: funciona com PATH vazio. Diretórios
relativos e links simbólicos nos diretórios são resolvidos por `cd -P`/`pwd -P`.
Execute o AppRun real, não um link simbólico avulso para esse arquivo fora do AppDir.

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
Na base 178adf5, `--version` ainda não existe e o daemon exige `--simulate`;
isso é pendência do Backend, não corrigida pelo wrapper de build.
