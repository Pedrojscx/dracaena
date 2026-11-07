"""quiz-helper: resolve questões do Cisco NetAcad pelo Chrome DevTools Protocol.

Lê a questão como texto do DOM (Playwright conectado ao Vivaldi do perfil
dedicado), consulta o Claude e age nos próprios elementos da página. Toda
ação passa por `guard.Guard`, a única função que clica.
"""
