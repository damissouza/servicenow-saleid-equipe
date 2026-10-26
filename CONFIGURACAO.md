# Configuracao local, campo por campo

Os valores de resolucao e seletores foram copiados da configuracao existente; e-mail, dominio pessoal, perfil e numeros reais de referencia foram retirados dos exemplos. Nao invente valores internos. `configurar.py` cria os arquivos efetivos ao lado dos scripts em `saleid`.

## config_conexao_historico_venda_ativa.json

Modelo: `saleid/config_conexao_historico_venda_ativa.example.json`.

| Campo | Tipo | O que controla |
|---|---|---|
| `instance_url` | texto | Origem HTTPS do ServiceNow, sem senha, token ou caminho de lista. |
| `connection_mode` | texto | Modo de conexao do navegador; o fluxo principal utiliza CDP. |
| `cdp_url` | texto | Endereco HTTP local de depuracao; somente localhost/127.0.0.1. |
| `browser` | texto | Tipo reconhecido pelo codigo; Brave funciona como Chromium pela conexao CDP. |
| `profile_dir` | texto | Pasta local do perfil dedicado, preenchida pelo configurador. Nao enviar ao Git. |

## config_inspecao.json

Modelo: `saleid/config_inspecao.example.json`.

| Campo | Tipo | O que controla |
|---|---|---|
| `matricula_selectors` | lista | Seletores CSS ja existentes dos campos de matricula. |
| `matricula_labels` | lista | Rotulos auxiliares mantidos do original; uso depende do caminho de leitura no inspecionador. |
| `franquia_selectors` | lista | Seletores CSS ja existentes dos campos de franquia. |
| `franquia_labels` | lista | Rotulos auxiliares mantidos do original; nao alteram a regra da RITM, que usa Aberto por. |

## config_resolucao.json

Modelo: `saleid/config_resolucao.example.json`.

| Campo | Tipo | O que controla |
|---|---|---|
| `assignee_email` | texto | E-mail do usuario ativo para selecao da carteira e atribuicao; altere aqui para cada operador. |
| `numbers_file` | texto | Arquivo local de chamados no modo de lista explicita. |
| `response_file` | texto | Arquivo local com comentario publico aprovado e assinatura do operador. |
| `reference_incident` | texto | INC real resolvido/encerrado para conferir os valores internos de resolucao. |
| `state_label` | texto | Rotulo do estado de destino dos incidentes, conferido com a referencia. |
| `resolution_code_label` | texto | Rotulo do codigo de resolucao exigido na referencia. |
| `resolution_option_label` | texto | Rotulo da anotacao de resolucao e texto conferido em close_notes. |
| `recurrent_label` | texto | Rotulo de reincidencia conferido na referencia. |
| `max_incidents` | inteiro | Limite maximo do lote; exceder interrompe sem executar lista parcial. |
| `plan_max_age_minutes` | inteiro | Validade da previa em minutos; a configuracao e a lista tambem precisam coincidir. |
| `reference_ritm` | texto | RITM real concluida e inativa para conferir encerramento. |
| `ritm_close_notes` | texto | Anotacao de encerramento enviada a SCTASK, conforme processo existente. |
| `resolution_confirmed_markers` | lista | Marcadores para os quais resposta e resolucao ja foram conferidas. |
| `selection_tag_references` | objeto | Mapa de nome do marcador para numeros reais que possuem esse marcador; nao sao inventados pelo configurador. |

## Onde o codigo le

`resolver_incidentes.settings` carrega config_resolucao e config_conexao, a lista e a resposta. `processar_chamados.inspect_for_preview` carrega config_inspecao. `resolve_user` resolve assignee_email no ServiceNow. `--tipo inc` e `--tipo ritm` usam previas separadas; nenhum arquivo deve ser copiado de uma pessoa para outra depois de preparado.

A senha da equipe e solicitada somente por `publicar_resultados.py` com entrada oculta, nao faz parte destes JSONs e nao deve ser adicionada a nenhum arquivo. O endereco do painel esta fixo na constante SITE do publicador, evitando envio acidental para outro servidor.


## Publicacao automatica

O e-mail da publicacao usa assignee_email. Se a conta autorizada no painel for diferente da atribuicao, a chave opcional panel_email no config_resolucao.json define apenas o acesso ao painel, sem alterar o responsavel no ServiceNow. A senha e solicitada no terminal e nunca deve ser incluida no JSON. Nenhuma chave nova e obrigatoria para ativar a publicacao.
