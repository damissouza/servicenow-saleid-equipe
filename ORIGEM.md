# Origem da copia

Arquivos copiados do modulo de historico do projeto existente. Nenhum arquivo de saida, backup ou configuracao pessoal foi copiado. `comentar_carteira.py` contem apenas a funcao `resolve_user`, identica a original. A coleta de atribuicao recebe a instancia HTTPS do cliente ja conectado, em vez de usar um dominio interno fixo. Os exemplos de configuracao conservam regras e seletores existentes, com dados pessoais e referencias de chamados removidos. A assinatura da resposta e preenchida na configuracao inicial. `historico_venda_ativa.py` passa a origem do cliente para o coletor de atividade, sem mudar a selecao do evento. `configurar.py`, `abrir_brave.ps1` e `publicar_resultados.py` sao adaptadores novos de preparacao/portabilidade/publicacao; nao resolvem chamados por conta propria.

## Arquivos e hashes de origem

| Arquivo | SHA256 de origem | Adaptacao |
|---|---|---|
| saleid/processar_chamados.py | f105b42fa44ae9f3c36b2ea67d39b4409755a43b736b696ac69e3b2cf3de529f | Copia integral |
| saleid/resolver_incidentes.py | 4cfa52c013200e26ffb4aca8a1b1c55387ebcddd06d51e9e457cb0d53dae749a | Portabilidade/remoção de referência em comentário |
| saleid/bulk_update.py | 07e77c9237de282ae75e2c8ba4bd9b93cf050ca6918e0cfa15b041486fcc3731 | Copia integral |
| saleid/numeros_chamados.py | 1a858983c78c0f403d00ee0ad16bb8238adbc0b80c7f6bd975298fc09fd04f71 | Copia integral |
| saleid/selecao_marcador.py | 93e3fb48148552667deda5b301b0b498991a4877f141eb4e20a3488850ed6016 | Copia integral |
| saleid/inspecionar_matriculas.py | 9c02be57df55675a6f74ed435f9c60baf7b4ee58ea2ecc955305f6e4ab53555f | Copia integral |
| saleid/dados_previsao.py | 31c319a223629e0f8c73a2a518ff3ffb253f07fb808ed65289237f29890328ca | Copia integral |
| saleid/previsao_sequencial.py | 02a8194462b84128df574fe7cb7161465e36aec8d4dc70c3ccac750fa8aec5d0 | Copia integral |
| saleid/previsao_paralela.py | 18ae65d107498ec95382f38b0ccce26e5d9fee5f0c0fbc5f412e52606aab056a | Copia integral |
| saleid/historico_venda_ativa.py | f82b28b0cdb29ca21253afc03ac3780b484e9467fa93ec4c3dceb272474b683f | Recebe origem HTTPS no coletor de atribuicao |
| saleid/atividade_atribuicoes.py | fde3d5a5de48dca54c520e37807eac5f686794d965f2d1320da2bd49482d1cfe | Portabilidade/remoção de referência em comentário |
| saleid/revisar_historico.py | 71f1dee9e418d6ca50144c19699999a635618f222f5565a6d25e60f06bce89fa | Copia integral |
| saleid/tabela_historico.py | 7c0648cc64f6535d834db602ce08629d85721f73d5ceebfba7ff87805954fca1 | Copia integral |
| saleid/previsao_chamados.css | 6180ca93fee8c8bc52969b8664d6bceacdb96d764cd7bc2e5c3c4f31ef91b960 | Copia integral |
| saleid/test_historico_venda_ativa.py | 3c6e97c922005f81e861214681f47256832940ef44492938bb9a90f5adf39ca3 | Copia integral |
| saleid/test_tabela_historico.py | 00d587495fb8ba2f13abab1f86f394b6d28fe41cbe0f83e1c4f7b2f91e192853 | Copia integral |
| saleid/test_processar_chamados.py | 310a2db067fd4326adef292ce0faa25bc537327ef760cf1ed366ce532f058399 | Copia integral |
| saleid/test_fluxo_coleta.py | 9dc68f944e2d96c927f85aa7e69118a38e42ca0e8c4aefbff4ff2140e3c58359 | Copia integral |

`validar_previsao.py` contem somente FIELDS e a funcao pura differences, copiados do validador existente de fluxo_unico para manter o teste de comparacao; nao inclui comandos de validacao ou acesso a navegador.

O favicon e o mesmo recurso estatico do painel existente; o configurador copia-o para a saida local dos relatorios.
