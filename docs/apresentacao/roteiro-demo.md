# Roteiro da demonstração — SynapseShop

Roteiro para conduzir a apresentação final sem consultar o código. Tempo total
estimado: **18 a 22 minutos**, com margem para perguntas.

## Pré-requisitos

- Docker Desktop/Engine com Compose v2 e pelo menos 6 GB livres.
- Portas livres: `8000` (API), `8001` (inventory), `8501` (Streamlit).
- `.env` local baseado em `.env.example`, com `GEMINI_API_KEY` preenchida
  **somente** se o bloco de IA real for executado.
- Navegador em `1366×768` ou maior, com zoom em 100%.

## Subida e preparação

```bash
docker compose up -d --build
docker compose exec api python api/manage.py seed_auth
docker compose exec api python api/manage.py seed_demo
docker compose exec api python api/manage.py indexar_docs
python scripts/validar_mvp.py
```

Se o smoke falhar, o próprio script imprime o passo e o status HTTP. Para
diagnóstico rápido:

```bash
docker compose ps
docker compose logs --tail=120 api
docker compose logs --tail=120 worker-kafka worker-pagamentos
python scripts/validar_compose.py
```

## Credenciais demo

- Administrador: `demo_admin`
- Cliente: `demo_user`

As senhas vêm de `SEED_ADMIN_PASSWORD` e `SEED_USER_PASSWORD` no `.env`; os
valores padrão de desenvolvimento estão documentados em
[`docs/autenticacao.md`](../autenticacao.md). Nunca projete o `.env`.

## Ordem sugerida

### 1. Catálogo e cache (3 min)

1. Abra `http://localhost:8000/app/`.
2. Faça login como `demo_admin`.
3. Mostre busca, filtro por categoria e ordenação no catálogo.
4. Abra `http://localhost:8000/api/v1/cache/metrics/` e mostre o hit rate.
5. Recarregue o catálogo e mostre `lookups`/`hits` crescendo.

**Plano B:** se o Redis estiver fora, a API degrada para o banco (fail-open);
explique que a listagem continua funcionando e que as métricas mostram
`cache_habilitado: false` ou erros de Redis.

### 2. Pedido (3 min)

1. Adicione dois produtos ao carrinho.
2. Clique em **Criar pedido** e mostre `id`, `status`, `total` e o bloco
   `evento`.
3. Clique em **Reenviar mesmo pedido**: a resposta deve ser **200** com o
   mesmo `id` e `evento.duplicado = true`.

**Plano B:** se o broker cair, a API responde **503** e o pedido fica em
`pendente_publicacao`. Mostre a recuperação:

```bash
docker compose exec api python api/manage.py republicar_pedidos
```

### 3. Pagamento e notificação (3 min)

1. Na seção **Pagamento**, informe o ID do pedido criado.
2. Escolha PIX, mantenha **Aprovado** e registre.
3. Mostre o polling: `registrado` → `aprovado`.
4. Mostre a notificação criada pelo worker.

**Plano B:** se o worker atrasar, acompanhe:

```bash
docker compose logs -f worker-pagamentos
```

Reenviar o mesmo POST de pagamento é idempotente (200); outro método/desfecho
no mesmo pedido retorna 409.

### 4. IA no modo mock (2 min)

1. Aba **Suporte**: cole um log curto e execute.
2. Aba **Texto-para-SQL**: use um exemplo clicável e mostre SQL, colunas e
   linhas.
3. Aba **Documentação**: pergunte “Como rodar os testes?” e mostre
   `sources` com caminho, intervalo e score.

**Plano B:** o mock é o padrão de CI e não depende de rede; se algo falhar,
confirme `LLM_PROVIDER=mock` e reinicie a API.

### 5. IA real com Gemini (3 min, opcional)

1. Confirme no `.env`:

   ```env
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=...
   LLM_MODEL=gemini-3.5-flash
   LLM_MODEL_SQL=gemini-3.5-flash
   LLM_MODEL_DOCS=gemini-3.5-flash
   LLM_TIMEOUT_SEGUNDOS=30.0
   ```

2. Reinicie a API: `docker compose up -d api`.
3. Repita uma pergunta em cada aba e mostre `/api/v1/llm/metrics/` com
   provedor, modelo, tokens e custo estimado.

**Plano B:** se houver erro 401/403 (chave), 429 (cota) ou timeout, volte para
`LLM_PROVIDER=mock` no `.env`, reinicie a API e siga a demo. Não existe
fallback automático — a troca é explícita.

### 6. Dashboards (3 min)

1. Abra `http://localhost:8501`.
2. Mostre receita total, ticket médio, receita por dia e os dois rankings de
   produtos (quantidade e receita).
3. Abra a página de **Desempenho da API** e mostre latência, status e hit rate.

**Plano B:** se o Streamlit não responder, valide
`http://localhost:8501/_stcore/health` e os logs do container `dashboard`; as
mesmas consultas podem ser demonstradas via Swagger/`/docs/`.

### 7. CI/CD (2 min)

1. Abra a aba **Actions** do repositório e mostre o último run verde.
2. Destaque os jobs `test-and-lint`, `docker-build`, `compose-smoke` e
   `publish`.
3. Mostre o digest da imagem publicado no DockerHub (sem exibir tokens).

**Plano B:** sem rede, mostre o resumo do último run salvo e rode localmente:

```bash
docker compose run --rm tests
python scripts/validar_compose.py
```

## Encerramento

- Retome o [checklist do MVP](checklist-mvp.md) e os dez requisitos.
- Reforce as limitações: mock padrão, RAG lexical, métricas por processo,
  front-end de demonstração e deploy simulado.
- Deixe o smoke reproduzível: `python scripts/validar_mvp.py`.
