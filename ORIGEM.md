# Origem da copia

Arquivos copiados do modulo de historico do projeto existente. Nenhum arquivo de saida, backup ou configuracao pessoal foi copiado. `comentar_carteira.py` contem apenas a funcao `resolve_user`, identica a original. A coleta de atribuicao recebe a instancia HTTPS do cliente ja conectado, em vez de usar um dominio interno fixo. Os exemplos de configuracao conservam regras e seletores existentes, com dados pessoais e referencias de chamados removidos. A assinatura da resposta e preenchida na configuracao inicial. `historico_venda_ativa.py` passa a origem do cliente para o coletor de atividade, sem mudar a selecao do evento. `configurar.py`, `abrir_brave.ps1` e `publicar_resultados.py` sao adaptadores novos de preparacao/portabilidade/publicacao; nao resolvem chamados por conta propria.

## Arquivos e hashes de origem

| Arquivo | SHA256 de origem | Adaptacao |
|---|---|---|
| saleid/processar_chamados.py | 4b769d7df8ee1c54d3f3f1d57bba07f6f1f39409984b2ea5743ff57cca6ff88b | Copia integral |
| saleid/resolver_incidentes.py | 50f66afa4a5a12c83f8dcd1f21124369e348258b9ac4e2139eb1e62d818330dc | Portabilidade/remoção de referência em comentário |
| saleid/bulk_update.py | b6268e83f6568b708ac47dd9e4a0100c0c8d65ae953415805de96fa9363d9e0c | Copia integral |
| saleid/numeros_chamados.py | 66f062f412b1ba393a522efa6395e9725662413f0d331a64d5466b65648aed8e | Copia integral |
| saleid/selecao_marcador.py | 56f2ec4c3e736563e221ae57255498d9808034f3aadd47224d52a1705136d6b2 | Copia integral |
| saleid/inspecionar_matriculas.py | 995ab9a65a3d8b4a1890a6f946c08a90b6cafe1823e0dfa281bf127fa7964773 | Copia integral |
| saleid/dados_previsao.py | e8e3593f586981e87a8e4a1b05fbb0b6a9842b8c0d7b74c9425005220344c131 | Copia integral |
| saleid/previsao_sequencial.py | cd4f2bb24883b6018dd1d59867bbaa8a3514c921c9bc518c5bf910f7e3c9ec81 | Copia integral |
| saleid/previsao_paralela.py | 5e5b57168a683c70aaad37a61d314a2957a4a67ab87e624e0ec1c55c60807373 | Copia integral |
| saleid/historico_venda_ativa.py | fae8e393cf9ff79c693e2ff0414c93e1bf9ed605df233e1a9c4042822bd7c92d | Recebe origem HTTPS no coletor de atribuicao |
| saleid/atividade_atribuicoes.py | fde3d5a5de48dca54c520e37807eac5f686794d965f2d1320da2bd49482d1cfe | Portabilidade/remoção de referência em comentário |
| saleid/revisar_historico.py | 71f1dee9e418d6ca50144c19699999a635618f222f5565a6d25e60f06bce89fa | Copia integral |
| saleid/tabela_historico.py | 7c0648cc64f6535d834db602ce08629d85721f73d5ceebfba7ff87805954fca1 | Copia integral |
| saleid/previsao_chamados.css | 6180ca93fee8c8bc52969b8664d6bceacdb96d764cd7bc2e5c3c4f31ef91b960 | Copia integral |
| saleid/test_historico_venda_ativa.py | 41a7bb9cccdec5a514969bead23560f390068bbc05f1a7384362b049b2915737 | Copia integral |
| saleid/test_tabela_historico.py | 00d587495fb8ba2f13abab1f86f394b6d28fe41cbe0f83e1c4f7b2f91e192853 | Copia integral |
| saleid/test_processar_chamados.py | cf53a925349535ec62980eba2bbc6143128930c403142d9b25afe0ecf966bf9d | Copia integral |
| saleid/test_fluxo_coleta.py | efa1b24585f81757756dcd4cb051f4a9b2d37f0dfd2c08707109e21b8427164e | Copia integral |

`validar_previsao.py` contem somente FIELDS e a funcao pura differences, copiados do validador existente de fluxo_unico para manter o teste de comparacao; nao inclui comandos de validacao ou acesso a navegador.

O favicon e o mesmo recurso estatico do painel existente; o configurador copia-o para a saida local dos relatorios.
