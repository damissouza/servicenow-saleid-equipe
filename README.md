# SaleID — execução pela equipe

Cópia dos scripts já utilizados para prever, conferir matrículas e resolver chamados de Venda Ativa. O código é público; **configurações pessoais, sessões, dados dos chamados e o histórico do painel continuam privados**.

Painel da equipe: https://historico-venda-ativa.vercel.app

Não há dados de produção, credenciais ou listas de chamados neste repositório. As referências e o e-mail devem ser preenchidos localmente. Acesso ao repositório **não concede acesso** ao ServiceNow nem ao painel.

## 1. Requisitos

- Windows e PowerShell.
- Python 3.11 ou superior e Brave instalado. Os testes locais desta distribuição foram executados com Python 3.14.
- Dependência: Playwright, conforme `requirements.txt`. Os demais módulos usam a biblioteca padrão.
- Sua conta ServiceNow com as mesmas permissões de leitura e escrita já exigidas pelos scripts existentes. Login e MFA são manuais no Brave.
- Para publicar: e-mail já autorizado no painel e senha da equipe obtida com a responsável por canal privado. Não use a senha do ServiceNow no publicador.
- Git para clonar, ou botão **Code → Download ZIP** no GitHub. Extraia o ZIP antes de executar.

## 2. Instalação

Abra o PowerShell na pasta deste repositório. **Todos os comandos abaixo partem dessa pasta**, não de `saleid`.

```powershell
py -3 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r .\requirements.txt
& ".\.venv\Scripts\python.exe" .\configurar.py
```

Não execute `playwright install`: a automação conecta ao Brave que você abre na porta local 9222.

O configurador pergunta seu e-mail, nome, origem HTTPS da instância, INC de referência, RITM de referência e referências do marcador. Ele grava somente arquivos locais. Se os arquivos já existem, não os sobrescreve: edite-os diretamente.

## 3. Onde mudar o e-mail de atribuição

Edite **`saleid/config_resolucao.json` → `assignee_email`** com o e-mail corporativo do operador que executará o lote. Esse é o e-mail consultado em `sys_user` para obter o responsável ativo de forma inequívoca.

O mesmo parâmetro também limita a seleção por marcador aos chamados atribuídos a esse usuário. Assim, cada colega trabalha com a própria carteira. A atribuição de INC e da SCTASK da RITM usa esse responsável, conforme o fluxo original.

Não coloque a senha nesse JSON. Ao mudar e-mail, resposta, parâmetros ou lista, gere **nova prévia**. Não reutilize prévia de outro operador.

## 4. Referências e resposta

- `reference_incident`: um INC real já resolvido ou encerrado, com os campos de resolução aprovados. Ele é somente lido para conferir os valores internos; não é incluído no lote por ser referência.
- `reference_ritm`: uma RITM real já em **Encerrado concluído**, inativa. Necessária para processar RITMs; pode ser configurada depois se trabalhar somente com INC.
- `selection_tag_references` → `Venda Ativa`: lista de chamados reais que já possuem esse marcador. Eles permitem descobrir o mesmo marcador por vínculos quando a tabela `label` não é acessível. Com lista vazia, o script tenta a consulta direta; HTTP 403 exige referência ou permissão, não remoção da validação.
- `saleid/resposta_resolucao.txt`: resposta pública aprovada. A assinatura é preenchida com o nome informado. Leia o texto completo e confira se a medida descrita **já foi realizada** no caso que será resolvido. O script não altera contratos nem executa a correção comercial descrita na resposta.
- `saleid/incidentes.txt`: lista local de INC/RITM para modo explícito, um por linha; começa vazia. No modo `--marcador`, a seleção é feita na carteira, e essa lista não é a origem do lote.

Não use chamados de referência de outra operação com campos diferentes. O pacote não contém referências reais nem inventa dados de resolução ausentes.

## 5. Abrir o Brave e concluir o login

```powershell
& .\abrir_brave.ps1
```

Abra sua instância ServiceNow nesse perfil e conclua o login/MFA. O perfil fica em `.brave_perfil`, não é versionado. A porta 9222 é apenas local; não a exponha na rede. Não abra duas instâncias usando o mesmo perfil/porta. O script não fecha seu navegador pessoal para liberar o perfil.

Se a política da empresa bloquear `.ps1`, não a desative. Abra o Brave manualmente, ajustando o caminho do executável:

```powershell
& "$env:LOCALAPPDATA\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir="$PWD\.brave_perfil"
```

## 6. Prévia e aplicação — primeiro teste com um chamado

Na primeira utilização, coloque **um chamado real autorizado** em `saleid/incidentes.txt`. O arquivo não contém exemplo de chamado real. Execute:

```powershell
& ".\.venv\Scripts\python.exe" .\saleid\processar_chamados.py prever --tipo inc
```

Confira `saleid/saida/previsao_chamados.html`, o resumo e os campos do chamado. Somente depois, execute:

```powershell
& ".\.venv\Scripts\python.exe" .\saleid\processar_chamados.py aplicar --tipo inc
```

O script pede a confirmação `RESOLVER N` para a quantidade preparada. Não pule a prévia. Não execute os scripts `bulk_update.py` ou o módulo de dependência `comentar_carteira.py` diretamente; a entrada da operação é `processar_chamados.py`.

## 7. Fluxo por marcador

Após validar o primeiro caso, para **INCs** da sua carteira com Venda Ativa:

```powershell
& ".\.venv\Scripts\python.exe" .\saleid\processar_chamados.py prever --tipo inc --marcador "Venda Ativa"
& ".\.venv\Scripts\python.exe" .\saleid\processar_chamados.py aplicar --tipo inc --marcador "Venda Ativa"
```

Para **RITMs**, faça uma prévia separada:

```powershell
& ".\.venv\Scripts\python.exe" .\saleid\processar_chamados.py prever --tipo ritm --marcador "Venda Ativa"
& ".\.venv\Scripts\python.exe" .\saleid\processar_chamados.py aplicar --tipo ritm --marcador "Venda Ativa"
```

As regras existentes foram mantidas: INC é resolvido; a RITM usa a única SCTASK ativa vinculada para atribuição, comentário e encerramento. Zero ou mais de uma SCTASK ativa impede preparação. A RITM em Pendente é excluída. Após encerrar a tarefa, a confirmação da RITM continua com espera/releituras do código original; não foi criado encerramento forçado da RITM nem reenvio automático de escrita incerta.

As opções `--workers 1` e `--visivel` continuam disponíveis. O padrão é sequencial, conectado ao Brave já aberto. `--workers 3` é opcional e pode aumentar instabilidade; não é recomendado como primeiro teste. Não há headless novo nesta cópia.

## 8. Completar o histórico local

Depois da resolução confirmada, o fluxo pede a tabela local de referência com **NOME_FANTASIA, MATRICULA, CPF e UC**, copiada da sua fonte de dados real. Uma matrícula por linha. CPF e UC permanecem texto, incluindo zeros à esquerda. `NULL` só deve ser informado quando realmente for o valor da sua fonte; não preencha dados por suposição.

Termine a tabela com `FIM`, confira e digite `GRAVAR`. Para retomar a revisão depois de cancelar:

```powershell
& ".\.venv\Scripts\python.exe" .\saleid\revisar_historico.py --pendentes
```

O modo sem `--pendentes` permite complementar/corrigir pela tabela, com a coluna opcional CHAMADO:

```powershell
& ".\.venv\Scripts\python.exe" .\saleid\revisar_historico.py
```

Isso **não resolve novamente** os chamados. As datas de resolução vêm das confirmações do ServiceNow; não são substituídas pela hora do lote. As regras de backup e diário são as mesmas do original.

## 9. Enviar ao nosso site

Esta distribuição usa um publicador próprio: **não precisa instalar sincronizador local para enviar os resultados**.

Primeiro confira o arquivo local sem conexão de rede:

```powershell
& ".\.venv\Scripts\python.exe" .\publicar_resultados.py --conferir
```

Depois publique:

```powershell
& ".\.venv\Scripts\python.exe" .\publicar_resultados.py
```

O programa mostra contagens, pede `PUBLICAR`, solicita e-mail autorizado e a senha do painel sem exibi-la/salvá-la. O destino é fixo: **https://historico-venda-ativa.vercel.app**. O envio transmite os dados reais do histórico para o painel privado da equipe, usando a mesma autenticação já existente.

Por baixo, o programa lê a versão compartilhada e chama `/api/historico/importar`. A importação:

- acrescenta novos pares chamado + matrícula;
- não remove registros dos colegas nem duplica reenvios;
- complementa campos antes vazios, sem apagar valores já preenchidos;
- recusa divergência em campo já preenchido e recusa alteração concorrente;
- mantém backup antes da escrita e os últimos 30 backups no servidor;
- não reenvia automaticamente uma escrita que falhou.

Se houver conflito, confira com a responsável antes de reenviar. O publicador não corrige silenciosamente informações já publicadas. Abra o painel e clique em **Atualizar histórico** para ver a versão compartilhada. O e-mail de acesso ao painel e o de atribuição têm funções diferentes; o primeiro precisa constar na lista privada de autorizados.

## 10. Configurações — campos existentes

Consulte [CONFIGURACAO.md](CONFIGURACAO.md) para a tabela de todas as chaves. Os três arquivos `.example.json` são modelos sem dados pessoais. Os arquivos efetivos são criados sem `.example` na pasta `saleid`.

## 11. Arquivos e responsabilidades

| Arquivo ou pasta | Uso |
|---|---|
| `configurar.py` | Cria configurações e resposta locais; sem acesso de rede. |
| `abrir_brave.ps1` | Abre Brave com perfil dedicado e CDP local. |
| `publicar_resultados.py` | Confere e importa resultados revisados no site privado. |
| `saleid/processar_chamados.py` | Entrada para prever e aplicar. |
| `saleid/resolver_incidentes.py` | Regras de resolução, validação da prévia e diário. |
| `saleid/inspecionar_matriculas.py` | Leitura dos campos, descrição e comentários, conforme o original. |
| `saleid/previsao_sequencial.py` e `previsao_paralela.py` | Coleta e segunda tentativa de leitura. |
| `saleid/historico_venda_ativa.py` | Base local, datas, revisão e backups. |
| `saleid/revisar_historico.py` e `tabela_historico.py` | Retomada da complementação local. |
| `saleid/atividade_atribuicoes.py` | Coleta somente de leitura da atribuição visível na atividade. |
| `saleid/bulk_update.py`, `numeros_chamados.py`, `selecao_marcador.py` | Dependências da conexão, proteção, seleção e números. |
| `saleid/comentar_carteira.py` | Somente `resolve_user`, sem comando de carteira nesta distribuição. |
| `saleid/dados_previsao.py` e `previsao_chamados.css` | Relatórios HTML/CSS locais. |
| `saleid/saida/` | Prévia, histórico, relatórios e diário; privado e fora do Git. |
| `saleid/backups/` | Backups locais; privados e fora do Git. |
| `ORIGEM.md` | Proveniência, hashes dos arquivos de origem e adaptações. |

## 12. Problemas comuns

| Mensagem/situação | Como proceder |
|---|---|
| Conexão com 9222 recusada | Abra o perfil dedicado, faça login e confirme a porta local. |
| HTTP 401/403 no ServiceNow | Confira login/MFA e permissões; não remova validações. |
| Referência não confere | Use referência real com os mesmos campos aprovados. |
| Marcador ausente/ambíguo | Confira grafia e referências reais em `selection_tag_references`. |
| Prévia expirada/configuração alterada | Gere nova prévia. Não aumente prazo para reaproveitar lote não conferido. |
| Resultado parcial/incerto | Confira o diário e o chamado com a responsável; não repita `aplicar` para corrigir histórico. |
| Revisão pendente | Retome `revisar_historico.py --pendentes`. |
| `.execution.lock` existe | Confira se há execução ativa. Não apague a trava de processo em andamento. |
| Painel recusa e-mail/senha | Use uma das contas autorizadas e a senha da equipe; não publique a senha no Git/chat. |
| Importação em conflito | Confira o painel e os dados locais. O programa não substitui dados divergentes automaticamente. |

## 13. Testes sem chamados reais

```powershell
& ".\.venv\Scripts\python.exe" -B -m unittest discover -s .\saleid -p "test_*.py"
& ".\.venv\Scripts\python.exe" -B -m unittest discover -s .\testes -p "test_*.py"
```

Os testes usam fixtures explicitamente fictícias, mocks e temporários. Nenhuma resolução de produção foi executada para preparar este repositório. Não execute os comandos `prever`/`aplicar` como teste automatizado de instalação.

## Segurança

Antes de usar Git, confira `git status`: somente código, modelos sem dados e documentação devem entrar. Não copie a pasta do seu projeto antigo inteira sobre este repositório. Não envie `saida`, `backups`, `.brave_perfil`, `.venv`, configurações efetivas, listas reais ou resposta assinada. O `.gitignore` ajuda, mas não substitui a revisão.

O código conserva opções internas de resolução existentes no projeto, sem credenciais. Outras instâncias/catálogos podem recusar esses valores; nesses casos o fluxo deve parar, conforme o original. Não invente um código substituto.
