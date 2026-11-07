# shellcheck shell=bash
# Capturas com grim na escala do monitor da janela e estabilização.

# qh_grab <saída.png> <"X,Y WxH"> <escala>
# Com timeout: o grim espera para sempre por um quadro de monitor apagado
# (DPMS desligado) ou de tela bloqueada.
qh_grab() {
    timeout 10 grim -g "$2" -s "$3" -t png "$1"
}

# Diferença em pixels entre duas imagens (magick compare -metric AE).
qh_image_diff() {
    local out
    out="$(magick compare -metric AE -fuzz 4% "$1" "$2" null: 2>&1)"
    out="${out%% *}"
    if [[ "$out" =~ ^[0-9]+(\.[0-9]+)?(e\+?[0-9]+)?$ ]]; then
        awk -v v="$out" 'BEGIN { printf "%d\n", v }'
    else
        printf '999999999\n'
    fi
}

# qh_grab_stable <saída> <geom> <escala> [intervalo_ms] [tolerância_px] [tentativas]
# Captura duas vezes com intervalo até a diferença ficar abaixo da tolerância.
qh_grab_stable() {
    local out="$1" geom="$2" scale="$3" interval="${4:-400}" tol="${5:-50}" tries="${6:-6}"
    local a="$out.a.png" b="$out.b.png" diff i
    qh_grab "$a" "$geom" "$scale" || return 1
    for (( i = 0; i < tries; i++ )); do
        qh_ms_sleep "$interval"
        qh_grab "$b" "$geom" "$scale" || { rm -f "$a"; return 1; }
        diff="$(qh_image_diff "$a" "$b")"
        if (( diff <= tol )); then
            mv -f "$b" "$out"
            rm -f "$a"
            return 0
        fi
        mv -f "$b" "$a"
    done
    # Não estabilizou: usa a última captura mesmo assim (o chamador registra).
    mv -f "$a" "$out"
    return 2
}
