# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Analistas de Operações de Suporte autorizados a tratar chamados de Venda Ativa no ServiceNow e publicar os resultados no painel da equipe.

## Product Purpose

Distribuir uma versão configurável do fluxo SaleID para que cada analista confira o lote, execute a tratativa e publique os resultados confirmados usando seu próprio acesso.

## Operating Context

- A interface de trabalho combina comandos no PowerShell e os sistemas web ServiceNow e Histórico de Venda Ativa.
- O operador inicia o Brave e faz login e MFA manualmente. A conexão do script usa a sessão local do navegador.
- O fluxo separa configuração, prévia, aplicação confirmada e publicação. A configuração de atribuição é individual.

## Capabilities and Constraints

- O repositório público distribui código, instruções e modelos fictícios. Configurações locais, sessões, dados de chamados e histórico ficam privados.
- O acesso ao código é independente das permissões do ServiceNow e do painel.
- A publicação usa a importação autenticada da equipe e preserva registros existentes. Tentativas incertas de escrita são registradas para conferência.

## Product Principles

1. Cada operador trabalha com as próprias permissões.
2. A prévia orienta a aplicação e o diário registra o resultado.
3. A publicação compartilha resultados confirmados e preserva o histórico anterior.
