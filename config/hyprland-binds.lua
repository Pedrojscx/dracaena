-- quiz-helper: atalhos para hyprland.lua (salve como ~/.config/hypr/quiz-helper.lua e carregue com loadfile)
local bin = os.getenv("HOME") .. "/.local/bin/"
hl.bind("SUPER + P", hl.dsp.exec_cmd(bin .. "quiz-loop"), { description = "quiz-helper: liga/desliga o loop" })
hl.bind("SUPER + SHIFT + P", hl.dsp.exec_cmd(bin .. "quiz-ask"), { description = "quiz-helper: pergunta manual" })
