#!/usr/bin/env bash
# glibc-max.sh <diretório> [limite]
#
# Mede o maior símbolo GLIBC_x.y exigido por cada ELF do diretório (objdump -T, com
# readelf --version-info como conferência) e imprime "<versão> <caminho>", do maior
# para o menor. GLIBC_PRIVATE não conta. Sai com 1 se algum ELF passar do limite
# (padrão 2.28) e lista esses arquivos em stderr.
set -euo pipefail

[[ $# -ge 1 && -d "$1" ]] || { echo "uso: $0 <diretório> [limite]" >&2; exit 2; }
root=$1
limit=${2:-2.28}
command -v objdump >/dev/null 2>&1 || { echo "glibc-max.sh: objdump não encontrado" >&2; exit 2; }

versions() { # arquivo -> versões GLIBC_x.y (sem o prefixo), uma por linha
    { objdump -T "$1" 2>/dev/null || true
      readelf --version-info --wide "$1" 2>/dev/null || true
    } | grep -o 'GLIBC_[0-9][0-9.]*' | sed 's/^GLIBC_//' || true
}

report=$(mktemp)
trap 'rm -f "$report"' EXIT
count=0
while IFS= read -r -d '' file; do
    head -c 4 "$file" 2>/dev/null | grep -q $'^\x7fELF' || continue
    count=$((count + 1))
    max=$(versions "$file" | sort -Vu | tail -n 1)
    printf '%s\t%s\n' "${max:-0}" "${file#"$root"/}" >>"$report"
done < <(find "$root" -type f -print0)

sort -t$'\t' -k1,1Vr "$report" | awk -F'\t' '{printf "%-6s %s\n", ($1 == "0" ? "-" : $1), $2}'
echo "ELFs medidos: $count; limite: $limit" >&2

over=0
while IFS=$'\t' read -r max file; do
    [[ "$max" != 0 ]] || continue
    if [[ "$max" != "$limit" && "$(printf '%s\n%s\n' "$limit" "$max" | sort -V | tail -n 1)" == "$max" ]]; then
        echo "ACIMA DO LIMITE GLIBC_$max: $file" >&2
        over=1
    fi
done <"$report"
exit "$over"
