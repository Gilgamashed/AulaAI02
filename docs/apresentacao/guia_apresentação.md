# Guia de Apresentação — SynapseShop

**Curso:** Programação Python Avançada com IA  
**Empresa simulada:** SynapseTech  
**Entrega:** MVP do SynapseShop — Aula 25  
**Duração sugerida:** 18 a 22 minutos + perguntas

Este guia liga cada item do MVP do `PROJECT_OVERVIEW.MD` ao que deve ser
mostrado na demo e responde às perguntas de `specs/preparativos_apresentacao.txt`.

---

## 1. Antes de começar (5 minutos)

### 1.1 Subir e preparar a stack

```bash
docker compose up -d --build
docker compose exec api python api/manage.py seed_auth
docker compose exec api python api/manage.py seed_demo --com-inventario
docker compose exec api python api/manage.py indexar_docs
```

Confira a saúde:

```bash
docker compose ps
python scripts/validar_compose.py
```

Rode o smoke **uma vez** antes da apresentação:

```bash
python scripts/validar_mvp.py
```

> Evite rodar o smoke várias vezes seguidas: o login tem cota de **5/min** e
> pode retornar **429** por alguns segundos. Se isso acontecer, aguarde a janela
> e rode novamente.

### 1.2 Abas que devem estar abertas

- Mock de front-end: <http://localhost:8000/app/>
- Inventário FastAPI (admin): <http://localhost:8000/app/inventario/>
- Streamlit: <http://localhost:8501>
- Swagger: <http://localhost:8000/docs/>
- ReDoc: <http://localhost:8000/redoc/>
- OpenAPI: <http://localhost:8000/docs/openapi.yaml>
- GitHub Actions: última execução da branch `dev`
- Opcional: logs dos workers em um terminal

### 1.3 Credenciais demo

- Administrador: `demo_admin`
- Cliente: `demo_user`

As senhas vêm de `SEED_ADMIN_PASSWORD` e `SEED_USER_PASSWORD` no `.env`.
Se não forem sobrescritas, os padrões de desenvolvimento estão documentados
em `docs/autenticacao.md`.

**Nunca mostre o `.env`, tokens JWT, a `GEMINI_API_KEY` ou os secrets do
DockerHub.**

### 1.4 Estado atual do CI

O último run da branch `dev` foi concluído com sucesso:

- Run: `42529862804`
- Commit: `c8067e9`
- Duração: ~2m54s

Abra a aba **Actions** e deixe esse run visível para o bloco de CI/CD.

---

## 2. Abertura — 1 minuto

**O que dizer:**

- O SynapseShop é o backend de uma loja online com catálogo, pedidos,
  pagamentos simulados, notificações e três recursos de IA.
- Foi construído incrementalmente com **SpecDD**, em 25 aulas.
- A arquitetura usa Django REST, FastAPI, PostgreSQL, Redis, Kafka/RabbitMQ,
  Streamlit e Gemini com fallback mock.
- O objetivo da apresentação é provar o fluxo ponta a ponta, não apresentar
  um front-end de produção.

**Frase de transição:**

> “Vou seguir os dez itens do MVP e mostrar, em cada um, a evidência executável.”

---

## 3. Roteiro pelos itens do MVP

### 3.1. Catálogo e cache — 3 min

**O que dizer:**

- CRUD de produtos com JWT e papéis.
- O catálogo usa **cache-aside** com Redis: a primeira leitura popula o cache;
  as seguintes usam o cache.
- Escritas invalidam as chaves; se o Redis cair, a API continua no banco
  (`fail-open`).

**O que fazer:**

1. Em `/app/`, faça login como `demo_admin`. O catálogo é recarregado
   automaticamente após o login: os botões de **Editar/Excluir** aparecem sem
   F5.
2. Mostre busca, filtro por categoria, filtro por status (`Ativos`/`Inativos`)
   e ordenação.
3. Abra `/api/v1/cache/metrics/` pelo botão **Métricas de cache** do `/app/`
   (o navegador não envia o Bearer ao abrir a URL diretamente).
4. Recarregue o catálogo e mostre `lookups`/`hits` crescendo.

**Evidência:** passo 3 do `validar_mvp.py`; testes de cache e catálogo.

**Plano B:** se o Redis estiver fora, explique o `fail-open` e mostre o painel
indicando cache desabilitado/erro.

---

### 3.2. Pedidos e evento `PedidoCriado` — 3 min

**O que dizer:**

- O total é calculado no servidor com os preços do catálogo.
- O pedido é gravado em `pendente_publicacao` e o evento é publicado **depois
  do commit** (`transaction.on_commit`).
- `Idempotency-Key` protege contra duplo clique e retry de rede.
- Se o broker estiver fora, a API responde **503** e o pedido pode ser
  republicado.

**O que fazer:**

1. Adicione dois produtos ao carrinho.
2. Clique em **Criar pedido**.
3. Mostre **201** com `id`, `status`, `total` e o bloco `evento`.
4. Clique em **Reenviar mesmo pedido**.
5. Mostre **200** com o mesmo `id` e `evento.duplicado=true`.

**Evidência:** passos 4 e 5 do `validar_mvp.py`; testes de idempotência.

**Plano B:** se o broker cair, mostre o 503 e rode:

```bash
docker compose exec api python api/manage.py republicar_pedidos
```

---

### 3.3. Pagamento, notificação, idempotência e DLQ — 4 min

**O que dizer:**

- O pagamento é processado de forma assíncrona pelo worker.
- O worker aplica o desfecho e cria a notificação na mesma transação.
- Há deduplicação no Redis e `UPDATE` condicional no banco.
- Falhas recuperáveis passam por retry com backoff; depois da escada, a
  mensagem vai para a **DLQ**.
- Os fluxos de pedidos e pagamentos têm tópicos, grupos e DLQs separados.

**O que fazer:**

1. Na seção **Pagamento**, use o ID do pedido criado.
2. Escolha **PIX**, mantenha **Aprovado** e registre.
3. Mostre o polling: `registrado` → `aprovado`.
4. Mostre a notificação criada na seção **Notificações do pedido**.
5. Opcional: marque **Simular falha (DLQ)**, mostre o aviso e acompanhe:

```bash
docker compose logs -f worker-pagamentos
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos
```

**Evidência:** passos 6 e 7 do `validar_mvp.py`; testes de pagamento,
notificação, retry e DLQ.

**Plano B:** se o worker atrasar, mostre os logs e explique que a UI continua
consultando por até 20 segundos.

---

### 3.4. Autenticação JWT, papéis e throttling — 2 min

**O que dizer:**

- Login com access/refresh token.
- Papéis `admin` e `user`; rotas administrativas retornam **403** para `user`.
- O login tem cota própria de **5/min**; as APIs têm `anon 20/min` e
  `user 100/min`.
- O throttling protege contra força bruta e abuso.

**O que fazer:**

1. Mostre `demo_admin` autenticado no `/app/`.
2. Faça logout e login como `demo_user`.
3. Tente abrir uma rota admin (cache ou LLM metrics) e mostre **403**.

**Evidência:** passo 2 do `validar_mvp.py`; testes de autenticação e
throttling.

**Plano B:** se o login retornar 429, aguarde a janela de 1 minuto (ou alguns
segundos, conforme o `Retry-After`) e tente novamente.

---

### 3.5. Assistente de suporte com IA — 2 min

**O que dizer:**

- Engenharia de prompt com dois modos: `summarize` e `explain`.
- A resposta é objetiva e em português.
- A camada de IA aplica redação de PII/segredos, timeout, retry e circuit
  breaker.
- O modo `auto` tenta Gemini e pode cair para o mock em indisponibilidade
  técnica.

**O que fazer:**

1. Aba **Suporte** no `/app/`.
2. Cole um log curto:
   ```text
   2026-11-08 10:00 ERROR timeout ao conectar no banco
   ```
3. Execute e mostre `answer`, `meta.tokens_prompt` e
   `meta.tokens_output`.

**Evidência:** passo 8 do `validar_mvp.py`; `test_assist_endpoint.py`.

**Plano B:** se o Gemini estiver lento, o fallback pode assumir. Mostre
normalmente e explique o modo `auto`.

**Plano B (cota):** a free tier do Gemini permite **20 requisições/dia**
(observado em 2026-11-16). Se o log trouxer HTTP 429, a cota acabou: pare os
ensaios, force `LLM_PROVIDER=mock` e reserve as requisições para a demo.

---

### 3.6. Consulta em linguagem natural → SQL — 3 min

**O que dizer:**

- O prompt recebe o schema permitido.
- A resposta é extraída e validada: apenas `SELECT`/`WITH`, sem DML/DDL, sem
  tabelas internas, com `LIMIT`.
- A execução ocorre em transação **READ ONLY** com `statement_timeout`.
- Perguntas fora do domínio devem retornar **422** com exemplos.

**O que fazer:**

1. Aba **Texto-para-SQL** como `demo_admin`.
2. Use um exemplo clicável.
3. Mostre o SQL, `columns`, `rows`, `row_count`, `truncated` e `meta.modelo`.
4. Opcional: faça uma pergunta fora do domínio e mostre **422** com `examples`.

**Evidência:** passo 9 do `validar_mvp.py`; testes de validação e execução
read-only.

**Plano B:** se quiser uma segunda visão, use a página **Consulta em Linguagem
Natural** do Streamlit, que também renderiza as linhas como tabela usando o
mesmo endpoint.

---

### 3.7. RAG de documentação com fontes — 3 min

**O que dizer:**

- README e OpenAPI são divididos em chunks e indexados localmente.
- Os embeddings são lexicais (TF-IDF), sem rede.
- O guardrail roda antes da LLM: sem chunk acima de `min_score`, a LLM não é
  chamada.
- A resposta deve citar `[1]`, `[2]`; o contexto é tratado como **dado**, não
  instrução (defesa contra prompt injection).

**O que fazer:**

1. Aba **Documentação**.
2. Pergunte: **“Como rodar a suíte de testes localmente?”**
3. Mostre `answer` e `sources` com `path`, `title`, `range` e `score`.
4. Faça uma pergunta fora do domínio para mostrar `sources: []` e o guardrail.

**Evidência:** passo 10 do `validar_mvp.py`; índice RAG construído; testes de
guardrail e citação.

**Plano B:** se `sources` vier vazio, rode `indexar_docs`, reformule a pergunta
ou reduza `min_score` com cautela.

---

### 3.8. Dashboards de vendas e desempenho — 3 min

**O que dizer:**

- O painel de vendas considera receita apenas de pedidos `processado`.
- Indicadores: receita total, ticket médio, receita por dia e top produtos por
  quantidade e por receita.
- O painel de desempenho mostra latência, status e hit rate do processo da API.
- A agregação usa SQLAlchemy Core com bind parameters; não há interpolação de
  SQL.

**O que fazer:**

1. Abra <http://localhost:8501>.
2. Mostre os cartões de vendas e o gráfico de **receita por dia**.
3. Mostre as abas de produtos: **Por quantidade** e **Por receita**.
4. Abra a página **Desempenho da API**.

**Evidência:** `tests/unit/test_dashboard_sales.py`; `seed_demo` com 20 pedidos
históricos.

**Plano B:** se o Streamlit não responder, valide
`http://localhost:8501/_stcore/health` e os logs do container `dashboard`.

---

### 3.9. Inventário FastAPI (admin-only) — 2 min

**O que dizer:**

- O inventário é um microsserviço **FastAPI** separado, com tabela própria
  (`inventory_items`) e CRUD real em `/api/v1/inventory`.
- A página `/app/inventario/` é servida pelo Django para manter o mesmo login
  e evitar CORS. O navegador chama `/api/v1/inventario/`; o Django valida o
  JWT/papel `admin` e encaminha para o FastAPI pela rede interna.
- O link **Inventário FastAPI** só aparece para `admin`; `demo_user` recebe
  `403` no proxy e não consegue listar nem alterar itens.
- O `seed_demo --com-inventario` já deixou cada produto ativo do catálogo com
  **10 a 30 unidades**; a tabela deve abrir com os itens já populados.
- A porta direta do FastAPI fica em `127.0.0.1` (Swagger/depuração local).

**O que fazer:**

1. Faça login como `demo_admin` e clique em **Inventário FastAPI** na seção
   **Operação**.
2. Mostre a tabela preenchida e crie um item extra ao vivo:
   - SKU: `INV-DEMO-001`
   - Nome: `Item de demonstração`
   - Quantidade: `10`
   - Reservado: `2`
   - Reposição: `3`
3. Mostre o item na tabela e o status **HTTP 201**.
4. Clique em **Editar**, altere a quantidade para `7` e mostre **HTTP 200**.
5. Tente criar o mesmo SKU novamente e mostre **409**.
6. Exclua o item e mostre **HTTP 204**.
7. Em outro terminal, rode `docker compose logs -f inventory` para provar que
   o CRUD foi executado pelo FastAPI.
8. Saia e entre como `demo_user`: o link não aparece; abra
   `/app/inventario/` diretamente e mostre **acesso restrito**.

**Evidência:** `tests/integration/test_inventory_proxy.py`,
`tests/integration/test_app_frontend.py` e o passo “Inventário admin via
proxy” do `validar_mvp.py`.

**Plano B:** se o FastAPI estiver fora, a página mostra `503` e o proxy não
expõe a URL interna. Verifique `docker compose ps` e os logs do `inventory`.

---

### 3.10. Testes, cobertura e documentação da API — 2 min

**O que dizer:**

- A suíte cobre Django, FastAPI, dashboard, mensageria, IA e o mock de
  front-end.
- Gate de cobertura: **85%**; estado atual: **578 testes** e **90,16%**.
- Ruff e mypy rodam no CI.
- O contrato OpenAPI 1.26.0 é servido em Swagger, ReDoc e YAML.

**O que fazer:**

1. Mostre o resultado do último `docker compose run --rm tests`.
2. Abra `/docs/`, `/redoc/` e `/docs/openapi.yaml`.
3. Opcional: mostre `htmlcov/index.html`.

**Evidência:** suíte verde; `ruff check .`; `mypy api services dashboard`.

**Plano B:** se a suíte não rodar ao vivo, mostre o resultado do CI e o
relatório local.

---

### 3.11. CI/CD — 2 min

**O que dizer:**

- Pipeline com lint, testes, build Docker, smoke do Compose e publicação
  simulada.
- Cache de dependências Python e cache de camadas Docker.
- Deploy é simulado; não há provisionamento real.

**O que fazer:**

1. Abra a aba **Actions** do GitHub.
2. Mostre o run **`42529862804`**, verde em ~2m54s.
3. Destaque os jobs `test-and-lint`, `docker-build`, `compose-smoke` e
   `publish`.
4. Mostre o digest publicado no DockerHub, sem exibir tokens.

**Evidência:** `.github/workflows/ci.yml`; `scripts/validar_compose.py` 5/5.

**Plano B:** sem rede, rode localmente:

```bash
docker compose run --rm tests
python scripts/validar_compose.py
```

---

## 4. Respostas às perguntas dos preparativos

### 4.1. Login

#### Qual é o tempo de throttling do login?

- O escopo `login` usa **5 requisições por minuto** por cliente/IP.
- O `anon` global usa **20/min** e o `user` autenticado usa **100/min**.
- Ao estourar, a API devolve **429** com indicação de espera. Aguarde a janela
  ou alguns segundos e tente novamente.
- Em testes, o `settings_test` eleva as cotas para 1000/min; o teste específico
  de throttling baixa o login para 1/min para provar o 429.

#### Como simular SQL Injection para provar a resiliência da autenticação?

O login usa o ORM do Django (consultas parametrizadas), não concatenação de
strings. Teste com payloads no campo `username` ou `password`:

```text
admin' OR '1'='1
demo_admin' --
" OR 1=1 --
' OR '1'='1' --
```

Exemplo com `curl` (o heredoc evita problemas de aspas no shell):

```bash
curl -i -X POST http://localhost:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{"username":"admin' OR '1'='1","password":"x"}
JSON
```

Resultado esperado:

- **401** (credencial inválida), sem token;
- nenhum **500**, nenhum bypass;
- após 5 tentativas na janela, **429** (throttling).

Para a demonstração de SQL Injection em consultas, use o script do dashboard:

```bash
docker compose run --rm dashboard python -m dashboard.simular_sqli
```

Ele usa o payload `abc' OR '1'='1` como **valor** em uma consulta SQLAlchemy e
devolve `mitigado: true`, mostrando que o payload não altera a estrutura.

> Não faça dezenas de tentativas antes da demo: você pode bloquear o login por
> alguns segundos.

#### Como entrar como `demo_admin` para o cache metrics não dar 401?

Há dois detalhes:

1. O usuário correto é **`demo_admin`** (underscore), não `demo-admin`.
2. Abrir `http://localhost:8000/api/v1/cache/metrics/` diretamente no navegador
   **não envia** o header `Authorization`. O navegador não usa o token que está
   no `sessionStorage` do `/app/` em uma navegação comum.

Formas corretas:

- No `/app/`, faça login como `demo_admin` e clique no botão **Métricas de
  cache**; o JavaScript adiciona o Bearer.
- No Swagger (`/docs/`), clique em **Authorize** e cole o access token.
- No Postman/Insomnia, use `Authorization: Bearer <access>`.
- No terminal:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo_admin","password":"<senha>"}' |
  python -c 'import json,sys; print(json.load(sys.stdin)["access"])')

curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/cache/metrics/
```

Se o login no `/app/` retornar 401:

- confirme `demo_admin` com underscore;
- confira a senha (`SEED_ADMIN_PASSWORD` ou padrão de desenvolvimento);
- rode `seed_auth` se o usuário não existir;
- se retornar 429, aguarde a janela de throttling.

### 4.2. Catálogo

#### Exemplos de produto para cadastrar ao vivo

Use o formulário **Cadastrar produto** no `/app/` como `demo_admin`:

| Campo | Exemplo 1 | Exemplo 2 | Exemplo 3 |
|---|---|---|---|
| Nome | Synapse Tab X1 | Synapse Buds Pro | Synapse Air 14 |
| Marca | Synapse | Synapse | Synapse |
| Modelo | X1 | Buds Pro | Air 14 |
| SKU | `TAB-SYN-X1` | `AUD-SYN-BUDS` | `NBT-SYN-AIR` |
| Preço | 1299.00 | 499.90 | 4299.00 |
| Categoria | Acessórios | Áudio | Notebooks |
| Garantia | 12 | 12 | 24 |
| Descrição | Tablet para demonstração | Fone Bluetooth | Notebook leve |

Para cadastrar via API, descubra o ID da categoria:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/categories/
```

E envie:

```bash
curl -X POST http://localhost:8000/api/v1/items/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Synapse Tab X1",
    "brand": "Synapse",
    "model": "X1",
    "sku": "TAB-SYN-X1",
    "price": "1299.00",
    "category": 4,
    "warranty_months": 12,
    "description": "Tablet para demonstração"
  }'
```

> O ID `4` é apenas exemplo; confirme em `/categories/`. O formulário do `/app/`
> já carrega as categorias e evita esse problema.

### 4.3. Pedidos

#### Informações sobre a DLQ

- Cada fluxo tem sua DLQ:
  - `pedidos.criados.dlq`
  - `pagamentos.registrados.dlq`
- Uma mensagem vai para a DLQ quando:
  - o contrato é inválido (terminal, direto para DLQ); ou
  - as tentativas de reentrega se esgotam.
- A escada padrão é **1 tentativa inicial + 3 reentregas** com backoff
  `5s → 15s → 45s`.
- A DLQ retém mensagens por **30 dias**; o tópico principal, 7 dias.
- Inspeção:

```bash
# Fluxo de pedidos (padrão)
docker compose exec api python api/manage.py inspecionar_dlq_kafka

# Fluxo de pagamentos
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos

# Reprocessar
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos --reprocessar
```

- `X-Simular-Falha: true` só é aceito quando a flag de desenvolvimento está
  ligada; ele marca a entidade para o worker falhar de propósito e validar a
  DLQ.

#### Como o Kafka atua nesse serviço?

- O **produtor** publica `PedidoCriado` em `pedidos.criados` e
  `PagamentoRegistrado` em `pagamentos.registrados`.
- O `worker-kafka` consome `pedidos.criados`; o `worker-pagamentos` consome
  `pagamentos.registrados` com `--fluxo pagamentos`.
- Cada fluxo tem **3 partições**, grupo de consumidores, tópicos de retry
  (`*.retry.1`, `.retry.2`, `.retry.3`) e DLQ próprios.
- O consumer usa `enable.auto.commit=false`; o commit é manual e acontece só
  depois do efeito ou da DLQ.
- A idempotência combina Redis (`SET NX EX`) com `UPDATE` condicional no banco.
- O paralelismo vem das partições: com 3 consumidores, cada um pode ficar com
  uma partição.

### 4.4. Pagamentos e notificações

#### O sistema de notificação por e-mail/SMS/push é funcional ou mock?

É **simulado e persistido**: o worker cria uma `Notificacao` no banco com
título, mensagem, canal e timestamp; o `/app/` e a API exibem esse registro.
**Não há envio real** por SMTP, Twilio ou provedor de push. O campo `canal`
(`email`, `sms`, `push`) é registrado e exibido, mas a entrega externa não faz
parte do escopo.

Frase sugerida:

> “A notificação é funcional no domínio: ela é criada de forma idempotente
> pelo worker e fica consultável. O transporte externo de e-mail/SMS/push é
> simulado por canal, sem integração com um provedor real.”

#### Como e qual worker funciona nesse serviço?

- `worker-pagamentos`: mesma imagem/código da API, comando
  `python api/manage.py consumir_pedidos --fluxo pagamentos`.
- Ele consome `pagamentos.registrados`, aplica o desfecho no pagamento e cria a
  notificação.
- `worker-kafka`: comando `python api/manage.py consumir_pedidos`; consome
  `pedidos.criados` e avança o pedido para `processado`.
- Os dois usam commit manual, retry/backoff e DLQ própria.

#### Explicando o polling

- **Polling da UI:** após registrar o pagamento, o `/app/` consulta
  `GET /api/v1/pedidos/{id}/pagamento/` a cada **1 segundo**, por até **20
  tentativas**, até o status sair de `registrado`.
- **Polling das notificações:** após o pagamento concluir, a UI consulta
  `GET /api/v1/notificacoes/?pedido={id}` por até 10 tentativas de 1 segundo.
- **Polling do worker Kafka:** o consumer usa `poll()` para buscar mensagens do
  broker; isso é diferente do polling da UI. O worker é orientado a eventos,
  não fica consultando o banco.
- **Polling do smoke:** o `validar_mvp.py` repete as consultas até o worker
  concluir ou estourar o timeout configurado.

### 4.5. IA

#### O que são `summarize` e `explain`?

- **`summarize`**: resume os logs de forma objetiva, destacando erros,
  anomalias e o que exige atenção.
- **`explain`**: explica o que os logs indicam, incluindo causa provável e
  próximo passo recomendado.
- Ambos respondem em português do Brasil e usam o mesmo `llm_service`.

#### Parâmetros do front-end (`0.2` e `256`)

- **`temperature=0.2`**: controla a aleatoriedade. Valores baixos deixam a
  resposta mais determinística e conservadora; `0.0` é o mais determinístico.
  SQL e RAG usam `0.0` fixo no backend.
- **`max_tokens=256`**: limite de tokens de **saída** da resposta. Valores
  maiores permitem respostas mais longas e custam mais; o backend também tem
  limites próprios (`ASK_SQL_MAX_TOKENS=500`, `ASK_DOCS_MAX_TOKENS=600`).

#### Redação de PII, timeout, retry e circuit breaker

- **Redação de PII/segredos:** antes de chamar o provedor, o `LlmService`
  substitui e-mail, CPF/CNPJ, telefone, IP, cartão, JWT/Bearer, chaves
  (`sk-...`) e pares `password=...` por placeholders como `[EMAIL]`, `[CPF_CNPJ]`
  e `[TOKEN]`. A resposta também é redigida antes de sair (defesa contra eco).
- **Timeout:** a chamada roda em um executor com deadline
  `LLM_TIMEOUT_SEGUNDOS` (30 s no Compose para o Gemini; 5 s é o default do
  código). Se estourar, vira `LlmTimeout`.
- **Retry:** falhas recuperáveis (timeout, conexão, 429, 5xx) são tentadas até
  `LLM_MAX_TENTATIVAS` (3 no código; o exemplo usa 2), com backoff exponencial
  e jitter; `429` respeita `retry_after` quando disponível.
- **Circuit breaker:** após 5 falhas consecutivas, o circuito abre por 30 s;
  depois entra em half-open e permite 2 sondas. Sucesso fecha; falha reabre.
- **Fallback `auto`:** se o Gemini estiver tecnicamente indisponível depois do
  retry/breaker, o mock da tarefa assume. Erro 400 e bloqueio de segurança não
  fazem fallback.

#### O Texto-para-SQL ainda mostra `[object Object]`?

Era um bug do renderizador do `/app/`, não do prompt nem do provedor. A API
devolve `rows` como uma lista de **objetos**
(`[{"status": "processado", "total": 20}]`), e o front-end assumia que cada
linha era um **array**, fazendo `String(objeto)`.

O `renderizarSql` foi corrigido para aceitar os dois formatos: se a linha for
array, usa direto; se for objeto, mapeia pelas colunas. A tabela do `/app/`
agora exibe os valores corretamente. Se você estiver com uma versão antiga do
template em cache, recarregue o navegador com `Ctrl+F5`.

A página **Consulta em Linguagem Natural** do Streamlit continua como segunda
visão/plano B, usando o mesmo endpoint.

#### Perguntas fora do contexto SQL dão timeout em vez de 422. É ok?

O comportamento desejado é **422** com `detail` e `examples`. O caminho é:

1. O prompt pede `NAO_SUPORTADO` quando a pergunta não cabe no schema.
2. A extração transforma `NAO_SUPORTADO` em `PerguntaNaoSuportada`.
3. A view devolve **422**.

Se o Gemini estiver lento e estourar o timeout:

- com `LLM_PROVIDER=auto`, o `LlmService` cai para o mock após o retry; o mock
  responde `NAO_SUPORTADO`, e a resposta final vira **422**;
- com `LLM_PROVIDER=gemini` estrito, o timeout vira **503**, sem fallback.

Recomendação para a demo: use `auto`, `LLM_MAX_TENTATIVAS=2` e
`LLM_TIMEOUT_SEGUNDOS=30`. Se ainda houver timeout, confira
`/api/v1/llm/metrics/` (`fallbacks`, `ultimo_motivo_fallback`).

#### A resposta do RAG sobre “Como rodar os testes?” está OK?

A resposta apresentada fala de `reports/junit.xml`, `reports/coverage.xml` e
`htmlcov/` porque o índice recuperou um trecho do README sobre **artefatos do
CI**. Isso é uma limitação de relevância lexical, não um erro do provedor:

- a resposta cita uma fonte real (`[1]`);
- o guardrail e a citação funcionaram;
- o trecho recuperado é sobre CI, não sobre o comando local.

Para melhorar a demo:

- pergunte **“Como rodar a suíte de testes localmente?”**;
- ou complemente: “O comando local é `docker compose run --rm tests`”;
- se quiser corrigir na documentação, adicione um FAQ curto no README com esse
  comando e rode `indexar_docs` novamente.

#### O Texto-para-SQL funciona no `/app/` e no Streamlit?

Sim, nos dois. O `/app/` envia a pergunta para `/api/v1/ask_sql/` e agora
renderiza `rows` como objetos ou arrays. A página **Consulta em Linguagem
Natural** do Streamlit autentica como `admin`, envia a mesma pergunta e
renderiza `rows` como `DataFrame`. Use o `/app/` como caminho principal da demo
e o Streamlit como segunda visão ou plano B.

### 4.6. Dashboards

#### Qual gráfico é usado para “receita por dia”? Não seria melhor barras?

Já é um gráfico de **barras**: `dashboard/app.py` usa
`st.bar_chart(receita_dia.set_index("data")["receita"])`. O Streamlit renderiza
barras verticais para `st.bar_chart`.

Se quiser mais controle visual (rótulos, tooltips, cores), a evolução seria
usar `st.altair_chart` ou Plotly, mas não é necessário para o MVP.

### 4.7. CI/CD

#### Explique a pipeline, o cache e as camadas Docker

**Pipeline (`.github/workflows/ci.yml`):**

1. `test-and-lint`
   - instala Python 3.12 e `requirements-dev.txt`;
   - roda `ruff check .`;
   - roda `mypy api services dashboard`;
   - roda `pytest` com cobertura e JUnit;
   - publica `reports/` e `htmlcov/` como artefatos.
2. `docker-build`
   - usa Buildx;
   - cache GHA (`type=gha`, `mode=max`);
   - constrói `synapseshop-api:test` e inspeciona a imagem.
3. `compose-smoke`
   - sobe `db`, `api` e `dashboard` com `--wait`;
   - usa `.github/compose.ci.yml`;
   - roda `scripts/validar_compose.py` (5 verificações);
   - em falha, mostra `ps` e logs; sempre derruba o ambiente.
4. `publish`
   - depende dos três jobs;
   - só publica em push para `main`, `master` ou `dev`, ou execução manual;
   - usa `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` (secrets);
   - tags `sha-<completo>`, branch e `latest` no branch padrão;
   - verifica o digest com `imagetools inspect`;
   - sem secrets, gera warning e não publica.

**Cache:**

- `actions/setup-python` com `cache: pip`, chave baseada em
  `requirements.txt`, `requirements-dev.txt`,
  `services/inventory/requirements.txt` e `dashboard/requirements.txt`.
- Buildx com cache GHA compartilhado entre build, smoke e publish.
- Docker usa cache mount do pip e copia os requirements antes do código para
  preservar as camadas.

**Camadas Docker:**

- API: multi-stage builder/runtime, imagem `python:3.12-slim`, usuário
  não-root, dependências instaladas no builder e copiadas para o runtime.
- Testes: Dockerfile separado com pytest, dependências da API, inventory e
  stubs de tipos; não infla a imagem de produção.
- Inventory e dashboard têm Dockerfiles próprios, também multi-stage quando
  aplicável.
- O `.dockerignore` exclui `.env`, `.venv`, caches e artefatos, evitando copiar
  segredos ou lixo para a imagem.

---

## 5. Fechamento — 1 a 2 minutos

- Retome os dez itens e diga que todos estão `ATENDIDO` no checklist.
- Reforce as limitações:
  - fallback de IA pode ter latência após retry/breaker;
  - RAG é lexical (TF-IDF);
  - notificações são persistidas/simuladas, sem provedor externo;
  - métricas são do processo da API, não do broker;
  - `/app/` é mock de apresentação;
  - o FastAPI direto é local-only e sem autenticação; o caminho admin-only é o
    proxy `/api/v1/inventario/`;
  - deploy é simulado.
- Frase final:
  > “O MVP prova o fluxo completo: catálogo → pedido → evento →
  > pagamento → notificação → IA → dashboards → testes → CI/CD.”

---

## 6. Cola rápida de comandos e URLs

```bash
# Subida e preparação
docker compose up -d --build
docker compose exec api python api/manage.py seed_auth
docker compose exec api python api/manage.py seed_demo --com-inventario
docker compose exec api python api/manage.py indexar_docs

# Smoke e qualidade
python scripts/validar_mvp.py
python scripts/validar_mvp.py --skip-ai
docker compose run --rm tests
python -m ruff check .
python -m mypy api services dashboard
python scripts/validar_compose.py

# SQL Injection controlado
docker compose run --rm dashboard python -m dashboard.simular_sqli

# Diagnóstico
docker compose ps
docker compose logs --tail=120 api
docker compose logs --tail=120 worker-kafka worker-pagamentos
docker compose exec api python api/manage.py inspecionar_dlq_kafka
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos
```

**URLs:**

- Mock front-end: <http://localhost:8000/app/>
- Inventário FastAPI (admin): <http://localhost:8000/app/inventario/>
- Swagger: <http://localhost:8000/docs/>
- ReDoc: <http://localhost:8000/redoc/>
- OpenAPI: <http://localhost:8000/docs/openapi.yaml>
- Streamlit: <http://localhost:8501>
- Inventory health: <http://127.0.0.1:8001/health> (local-only)
- Inventory Swagger: <http://127.0.0.1:8001/docs> (local-only, sem auth)

---

## 7. Segurança e limitações para comentar

- A `GEMINI_API_KEY` fica apenas no `.env` (gitignored) e no processo da API;
  nunca é devolvida por endpoint, impressa ou copiada para a imagem.
- `.dockerignore` exclui `.env` e `.env.*`.
- JWT com access/refresh, papéis e throttling.
- SQL injection: ORM/bind parameters no login e consultas do dashboard;
  transação read-only no texto-para-SQL.
- Redação de PII antes do provedor e na resposta.
- Logs não exibem chave, prompt ou resposta bruta.
- A demo não deve mostrar tokens, `.env`, DevTools com `sessionStorage` ou
  secrets do DockerHub.
- O front-end usa `textContent`/DOM, não `innerHTML`; não persiste token em
  `localStorage`, cookie ou URL.

Boa apresentação! 🚀
