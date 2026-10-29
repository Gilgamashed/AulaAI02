# Consulta de Dados em Linguagem Natural / Texto-para-SQL (Aula 21)

## Objetivo

Permitir que uma pergunta de negócio em português seja traduzida em **uma
consulta SQL somente leitura**, executada no PostgreSQL e exibida em uma tabela
no painel Streamlit — sem dar ao modelo (nem ao usuário) poder de escrita.

```
pergunta → prompt (schema) → LlmService → extração → validação → execução read-only
```

Nenhuma etapa é opcional: mesmo que o provedor devolva um SQL perfeito, ele
passa pela validação e roda dentro de uma transação `READ ONLY`.

## Arquitetura

```
api/core/ask_sql/
├── constantes.py   # allow-list de tabelas/colunas, relacionamentos, glossário
├── schema.py       # DDL/describe enviado ao prompt + checagem de consistência
├── prompt.py       # regras do system prompt e montagem das mensagens
├── extracao.py     # normaliza a resposta (markdown, texto antes, NAO_SUPORTADO)
├── validacao.py    # barreira de segurança do SQL gerado
├── execucao.py     # transação read-only + statement_timeout + serialização
├── servico.py      # orquestra o pipeline (limites vindos das settings)
├── serializers.py  # contrato de entrada {question}
└── views.py        # POST /api/v1/ask_sql/ e mapa de erros HTTP

api/core/llm/
├── mock_sql.py     # provedor determinístico (mesma porta ProvedorLlm)
└── servico.py      # fábrica por tarefa: assist | sql

dashboard/
├── ask_sql.py                              # cliente HTTP (stdlib urllib)
└── pages/3_Consulta_em_Linguagem_Natural.py # UI Streamlit
```

## Por que um provedor mock

A Aula 14 decidiu que o provedor de IA do projeto é um mock em memória, sem
rede e sem credenciais. O texto-para-SQL mantém a decisão: `ProvedorMockSql`
cumpre `core.llm.portas.ProvedorLlm` e traduz **padrões de negócio** em SQL.
O que é mock e o que é real:

| Parte | Natureza |
| --- | --- |
| Tradução português → SQL | mock determinístico |
| Prompt com schema, extração, validação, execução read-only, contrato HTTP, testes | real |

Um adaptador de LLM real entra pela mesma porta, selecionado pela fábrica
(`criar_llm_service(tarefa="sql")`), sem tocar em validação/execução.

`criar_llm_service()` virou fábrica **por tarefa** (`assist` e `sql`), com
singleton e circuit breaker separados: uma falha no assistente não abre o
circuito do texto-para-SQL.

## Schema exposto ao modelo

O prompt não recebe introspecção livre do banco. Recebe uma allow-list
explícita, definida em `core/ask_sql/constantes.py`:

| Tabela | Papel |
| --- | --- |
| `auth_user` | usuários/clientes (sem `password`) |
| `core_pedido` | pedidos e estado do processamento |
| `core_pagamento` | pagamentos |
| `core_notificacao` | notificações |
| `core_item` | produtos do catálogo |
| `core_category` | categorias |

Ficam de fora `core_requisicao_metrica`, `django_*`, `auth_group*`,
`auth_permission`, `auth_user.password`, `idempotency_key` e `transacao_id`.
O teste `tests/unit/test_ask_sql_schema.py` compara a allow-list com os models
do Django, então uma coluna renomeada quebra a suíte em vez de quebrar o
endpoint em produção.

`enderecos_entrega` é citada na spec como exemplo de tabela do domínio, mas
**não existe** no SynapseShop. O prompt declara a ausência e perguntas sobre
endereço retornam **422** — em vez de inventar tabela/colunas.

## Contrato HTTP

`POST /api/v1/ask_sql/` — JWT obrigatório, papel **admin** (`IsAdminRole`):
a consulta pode ler pedidos, pagamentos e usuários de toda a base. O mesmo
critério de `/cache/metrics/` e `/llm/metrics/`.

Requisição:

```json
{ "question": "Quais os 5 últimos usuários cadastrados?" }
```

Resposta (200):

```json
{
  "question": "Quais os 5 últimos usuários cadastrados?",
  "sql": "SELECT id, username, email, first_name, last_name, is_active, date_joined\nFROM auth_user\nORDER BY date_joined DESC\nLIMIT 5",
  "columns": ["id", "username", "email", "first_name", "last_name", "is_active", "date_joined"],
  "rows": [{"id": 4, "username": "cliente3", "email": "", "first_name": "", "last_name": "", "is_active": true, "date_joined": "2026-10-28T12:00:00+00:00"}],
  "row_count": 1,
  "truncated": false,
  "meta": {"tokens_prompt": 812, "tokens_output": 32, "modelo": "mock-sql"}
}
```

| Campo | Significado |
| --- | --- |
| `sql` | consulta **validada e já com `LIMIT`** aplicado/clampado |
| `columns` | nomes na ordem devolvida pelo cursor |
| `rows` | linhas serializadas (Decimal → float, data → ISO-8601) |
| `row_count` | quantidade devolvida (não o total da tabela) |
| `truncated` | `true` quando havia mais linhas que o teto |
| `meta` | tokens e modelo usados |

| Status | Quando |
| --- | --- |
| `400` | `question` ausente, vazia, não textual ou > 500 caracteres |
| `401` | sem JWT |
| `403` | autenticado sem papel admin |
| `422` | pergunta fora do domínio (com `examples`), SQL ausente/proibido ou falha de execução |
| `500` | camada de IA mal configurada |
| `502` | provedor devolveu resposta inválida |
| `503` | provedor ou banco indisponível |

## Segurança em camadas

### 1. Prompt

Regras explícitas: apenas `SELECT`/`WITH`, sem DML/DDL, sem `SELECT *`, sem
comentários, sem funções de sistema, `JOIN ... ON` explícito, `LIMIT` máximo e
`NAO_SUPORTADO` para o que o schema não responde.

### 2. Validação (`validacao.py`)

A barreira que **não depende** de o modelo obedecer:

- um único comando, começando por `SELECT` ou `WITH`;
- sem comentários (`--`, `/* */`), identificadores entre aspas ou literais de
  dólar;
- allow-list das tabelas (inclusive `public.<tabela>`) e das colunas
  qualificadas (resolvendo aliases);
- bloqueio de colunas sensíveis, `SELECT *`/`tabela.*`, `FOR UPDATE/FOR SHARE`,
  `pg_catalog`, `information_schema` e funções perigosas (`pg_sleep`,
  `pg_read_file`, `dblink`, `nextval`, `set_config` etc.);
- `LIMIT` obrigatório, numérico e limitado a `ASK_SQL_MAX_LINHAS`.

A análise mascara o conteúdo de literais de texto antes de procurar palavras e
tabelas — `WHERE status = 'from core_pedido; drop'` é um valor, não SQL.

### 3. Execução (`execucao.py`)

- `SET TRANSACTION READ ONLY` antes da consulta;
- `set_config('statement_timeout', <ms>, true)` local da transação;
- `fetchmany(max_linhas + 1)` para detectar truncamento sem carregar tudo;
- erro do PostgreSQL vira 422 (consulta inválida) ou 503 (banco fora).

O teste `test_transacao_read_only_recusa_escrita` tenta um `INSERT` pelo mesmo
caminho e prova que o banco recusa e que nenhuma linha é gravada.

## Painel Streamlit

Página multipage `dashboard/pages/3_Consulta_em_Linguagem_Natural.py`:

1. login em `POST /api/v1/auth/token/`; o JWT fica em `st.session_state`;
2. campo de pergunta + seletor de exemplos;
3. `st.code(sql, language="sql")` com a consulta gerada;
4. métricas de linhas/truncamento e `st.dataframe` com o resultado;
5. `401` limpa a sessão e volta ao login; `422` mostra os exemplos aceitos.

O dashboard **não executa SQL**: chama a API por HTTP (`DASHBOARD_API_URL`).
Assim validação e transação read-only existem em um único lugar. A lógica
testável vive em `dashboard/ask_sql.py` (biblioteca padrão apenas); as páginas
executam UI já no import e ficam fora da cobertura (`pyproject.toml`).

## Configuração

```env
LLM_MODEL_SQL=mock-sql
ASK_SQL_MAX_LINHAS=200
ASK_SQL_TIMEOUT_MS=3000
ASK_SQL_MAX_TOKENS=500
ASK_SQL_LOG_LEVEL=INFO
DASHBOARD_API_URL=http://api:8000
```

`ASK_SQL_MAX_LINHAS` é o teto de linhas (o `LIMIT` é aplicado ou clampado);
`ASK_SQL_TIMEOUT_MS` é o `statement_timeout` local; `ASK_SQL_MAX_TOKENS` é o
teto pedido ao provedor. O logger JSON `core.ask_sql` registra pergunta não
suportada, SQL proibido e falha de execução.

## Roteiro de teste manual

```bash
docker compose up -d --build
docker compose exec api python api/manage.py seed_auth
```

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/auth/token/' `
  -ContentType 'application/json' `
  -Body (@{ username='demo_admin'; password='demo-admin@Synapse2026' } | ConvertTo-Json -Compress)
$h = @{ Authorization = "Bearer $($login.access)" }

foreach ($q in @(
  'Quais os 5 últimos usuários cadastrados?',
  'Qual a soma do valor dos últimos 3 pedidos?',
  'Quais usuários fizeram mais pedidos?'
)) {
  Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/v1/ask_sql/' `
    -Headers $h -ContentType 'application/json' `
    -Body (@{ question = $q } | ConvertTo-Json -Compress) |
    ConvertTo-Json -Depth 6
}
```

No painel: [http://localhost:8501](http://localhost:8501) → **Consulta em
Linguagem Natural** → login `demo_admin` / `demo-admin@Synapse2026` → escolher
um exemplo → **Consultar**.

## Testes

| Arquivo | Cobertura |
| --- | --- |
| `tests/unit/test_ask_sql_schema.py` | allow-list × models, colunas sensíveis, contexto |
| `tests/unit/test_ask_sql_validacao.py` | DML/DDL, `SELECT *`, allow-list, `LIMIT`, literais |
| `tests/unit/test_ask_sql_extracao.py` | markdown, texto antes, `NAO_SUPORTADO`, `;` |
| `tests/unit/test_ask_sql_mock.py` | padrões de negócio → SQL válido |
| `tests/unit/test_dashboard_ask_sql.py` | login, erros HTTP, normalização |
| `tests/integration/test_ask_sql_endpoint.py` | 401/403/400, DoD, SQL malicioso, read-only |

## Limitações registradas

- O mock cobre os padrões de negócio documentados; **não é linguagem natural
  irrestrita**. Perguntas fora dos padrões recebem 422 com exemplos.
- A transação read-only e o `statement_timeout` protegem contra mutação e
  consultas caras, mas não substituem um papel de banco exclusivamente
  read-only (evolução futura).
- O painel não monta SQL: toda a garantia fica na API.
