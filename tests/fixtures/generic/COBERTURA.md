# Cobertura sintética genérica

Base medida: `e44b6aa`. Adaptadores sem perfil; nenhuma consulta externa ou ação durante a medição.

Reproduzir: `PYTHONPATH=lib:tests/py python tests/py/generic_coverage.py`.
Para atualizar a tabela e observações: acrescente `--write`.

`ok`: tipo, cardinalidade, contagem MULTI e enunciado presentes (confiança >= 0,6 no generalizado).
`parcial`: encontrou questão, mas algum desses critérios divergiu. `falha`: não encontrou a questão esperada.
Nas negativas, `ok` significa recusa correta: nenhuma questão proposta. Não significa suporte ao controle.
A chamada é `locate(page.main_frame)`: a travessia de iframe deve ser feita pelo próprio adaptador.
A medição não prova resposta correta, navegação nem detecção de fim pela guarda.

| Tipo de tela | Fixture | Shadow / iframe | Heurístico | GeneralAdapter | Observação medida |
| --- | --- | --- | --- | --- | --- |
| Radio em fieldset e legend | `radio_rotulos.html` | não / não | ok | ok | heuristic: SINGLE:3, contagem=None; general: SINGLE:3, contagem=None |
| Checkbox com contagem no enunciado | `checkbox_contagem.html` | não / não | ok | ok | heuristic: MULTI:5, contagem=3; general: MULTI:5, contagem=3 |
| Select nativo único | `select_unico.html` | não / não | ok | ok | heuristic: DROPDOWN:[3], contagem=None; general: DROPDOWN:[3], contagem=None |
| Vários selects em frase | `selects_frase.html` | não / não | parcial | ok | heuristic: DROPDOWN:[2], contagem=None; general: DROPDOWN:[2, 3, 4], contagem=None |
| listbox ARIA selecionável | `lista_aninhada.html` | não / não | ok | ok | heuristic: SINGLE:3, contagem=None; general: SINGLE:3, contagem=None |
| radiogroup ARIA selecionável | `radio_aria.html` | não / não | ok | ok | heuristic: SINGLE:3, contagem=None; general: SINGLE:3, contagem=None |
| Shadow DOM aberto aninhado | `shadow_aninhado.html` | sim / não | ok | ok | heuristic: SINGLE:3, contagem=None; general: SINGLE:3, contagem=None |
| Questão em iframe srcdoc | `quadro_srcdoc.html` | não / sim | falha | ok | heuristic: nenhuma questão; general: SINGLE:3, contagem=None |
| Formulário paginado com Próxima | `paginas_locais.html` | não / não | ok | ok | heuristic: SINGLE:3, contagem=None; general: SINGLE:3, contagem=None |
| Resultado e resumo somente leitura | `resumo_leitura.html` | não / não | ok | ok | heuristic: nenhuma questão; general: nenhuma questão |
| Botões sem papel ou estado | `botoes_neutros.html` | não / não | ok | ok | heuristic: nenhuma questão; general: nenhuma questão |
| Campo de digitar editável | `campo_editavel.html` | não / não | ok | ok | heuristic: nenhuma questão; general: nenhuma questão |
| Arrastar entre regiões | `arraste_regioes.html` | não / não | ok | ok | heuristic: nenhuma questão; general: nenhuma questão |

## Diferenças em relação ao corpus existente

Os tipos básicos já existem no corpus. Estes arquivos acrescentam variantes estruturais, sem copiar ou alterar o corpus ou compat.

- `radio_rotulos.html`: Rótulos externos por for/id dentro de um fieldset isolado; corpus usa rótulos envolventes.
- `checkbox_contagem.html`: Cinco opções, contagem três e rótulos externos; corpus usa contagem duas.
- `select_unico.html`: Uma lacuna isolada com placeholder desabilitado; corpus contém conjuntos de selects.
- `selects_frase.html`: Três lacunas com cardinalidades distintas e placeholders desabilitados; corpus tem duas.
- `lista_aninhada.html`: Opções em wrappers de apresentação, com seleção por clique ou teclado; corpus usa filhos diretos.
- `radio_aria.html`: Radios ARIA em divs com spans e wrappers; corpus usa botões.
- `shadow_aninhado.html`: Dois níveis de shadow roots; corpus contém componentes irmãos com um nível.
- `quadro_srcdoc.html`: Documento inline; corpus carrega um arquivo separado por src.
- `paginas_locais.html`: Troca local de fieldsets e exclusão da questão oculta; corpus tem apenas a tela estática de navegação.
- `resumo_leitura.html`: Resumo sem botões, nota ou envio; corpus contém resumo com ações globais.
- `botoes_neutros.html`: Grade com botões dentro de wrappers, sem semântica de seleção; variante negativa estrutural.
- `campo_editavel.html`: Editor contenteditable; corpus usa input de texto.
- `arraste_regioes.html`: Elemento arrastável em grade e região de destino; corpus usa lista ordenável.

O manifesto usa inteiro para alternativas de escolha e lista por lacuna para DROPDOWN; placeholders não contam.
Nas negativas, o número descreve controles candidatos na página, sem afirmar que são alternativas suportadas.
`paginas_locais.html` contém duas etapas, mas a medição inicial considera só a primeira; o botão Próxima não é acionado.
Seleção ARIA é verificada separadamente pelos testes, sempre por Guard.perform.
