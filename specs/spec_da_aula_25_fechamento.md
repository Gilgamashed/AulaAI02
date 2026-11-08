# Spec da Aula 25 — Fechamento do MVP, Evidências e Apresentação

## 1. Objetivo

Fechar o MVP do SynapseShop com evidências reproduzíveis do cumprimento do
Definition of Done (DoD) do curso, massa de dados de demonstração e um
dashboard de vendas que represente explicitamente o requisito
"Dashboards de vendas e de desempenho da API".

Esta spec **não** cria funcionalidades de negócio novas: ela audita o que já
existe, torna a apresentação repetível e cobre as lacunas de evidência e de
dados.

## 2. Contexto

O arquivo `specs/preparativos_apresentacao.txt` pede a verificação do MVP e a
preparação da apresentação final. O backend já entrega catálogo com cache,
pedidos com `PedidoCriado`, pagamento/notificação assíncronos com
idempotência e DLQ, JWT com papéis, assistentes de IA, dashboards, testes,
OpenAPI e CI/CD.

As lacunas desta spec são:

- não há uma matriz formal que ligue cada item do MVP à implementação e à
  evidência executável;
- não há um smoke ponta a ponta que prove o fluxo completo em uma única
  execução;
- o banco sobe vazio (apenas usuários do `seed_auth`), o que deixa o painel
  de vendas sem dados para a demo;
- o painel de pedidos não exibe explicitamente receita por dia, ticket médio
  e produtos mais vendidos.

## 3. Requisitos Detalhados

### 3.1. Checklist do MVP

Criar `docs/apresentacao/checklist-mvp.md` com uma matriz contendo, para cada
item do MVP:

- requisito original;
- implementação correspondente (caminho de arquivo/módulo);
- testes automatizados que cobrem o item;
- comando ou rota que produz a evidência em execução;
- status (`ATENDIDO`, `PARCIAL` ou `PENDENTE`);
- limitações conhecidas.

A matriz deve cobrir exatamente os dez itens do arquivo de preparativos:

1. cadastro e listagem de produtos com cache no catálogo;
2. criação de pedidos com publicação de `PedidoCriado`;
3. processamento assíncrono de pagamento e notificação com idempotência e
   DLQ;
4. autenticação JWT com papéis de administrador e cliente;
5. assistente de suporte via IA com engenharia de prompt;
6. consulta de dados de negócio em linguagem natural (texto-para-SQL);
7. assistente de dúvidas baseado na documentação (RAG) com citação de
   fontes;
8. dashboards de vendas e de desempenho da API;
9. suíte de testes automatizados e documentação completa da API;
10. pipeline de CI/CD.

O checklist deve registrar como limitações, no mínimo:

- os provedores de IA são mock por padrão e podem ser trocados por Gemini
  (spec `spec_da_aula_25_gemini.md`);
- os embeddings do RAG são lexicais (TF-IDF), sem modelo neural;
- o dashboard de desempenho mede o processo da API, não profundidade de
  fila do broker;
- o front-end é um mock de apresentação (spec
  `spec_da_aula_25_frontend.md`), não um produto de produção.

### 3.2. Smoke ponta a ponta (`scripts/validar_mvp.py`)

Criar um script Python 3.12+, usando apenas a biblioteca padrão, que valide a
stack já em execução e devolva código de saída `0` somente se todos os passos
obrigatórios passarem.

Interface:

```bash
python scripts/validar_mvp.py
python scripts/validar_mvp.py --base-url http://localhost:8000 --skip-ai
python scripts/validar_mvp.py --inventory-url http://localhost:8001 --timeout 30
```

Passos obrigatórios:

1. `GET /health` da API e `GET /health` do inventory;
2. login com `demo_admin` e `demo_user` em `/api/v1/auth/token/`;
3. `GET /api/v1/items/` duas vezes e comprovação de incremento de cache em
   `GET /api/v1/cache/metrics/` (quando o cache estiver habilitado);
4. criação de pedido em `POST /api/v1/pedidos/` com `Idempotency-Key`;
5. repetição do mesmo POST e verificação de idempotência (200 e mesmo
   `id`);
6. `POST /api/v1/pedidos/{id}/pagamento/` com pagamento aprovado;
7. polling curto de `GET /api/v1/pedidos/{id}/pagamento/` e de
   `GET /api/v1/notificacoes/?pedido={id}` até o worker concluir, com
   timeout configurável;
8. `POST /api/v1/assist/` com um log curto;
9. `POST /api/v1/ask_sql/` com uma pergunta suportada;
10. `POST /api/v1/ask_docs/` com uma pergunta técnica, exigindo ao menos uma
    fonte citada;
11. `GET /app/` (mock de front-end);
12. `GET /health` do dashboard Streamlit.

Regras:

- `--skip-ai` transforma os passos 8–10 em `SKIP`, nunca em `PASS`;
- falhas de rede e respostas HTTP inesperadas devem ser reportadas com o
  status e o corpo resumido;
- a saída deve ser um resumo legível e um JSON final com
  `ok`, `passos`, `skipped` e `falhas`;
- nenhuma credencial deve ser impressa;
- o script não deve depender de `requests`, `docker` ou do Django.

### 3.3. Massa de demonstração (`manage.py seed_demo`)

Criar o management command `api/core/management/commands/seed_demo.py`,
idempotente, manual e sem dependência de rede.

Deve criar:

- ao menos **4 categorias** (ex.: smartphones, notebooks, áudio, acessórios);
- ao menos **12 produtos** ativos, com SKUs no formato `XXXX-AAAA-BBBB`,
  preços variados e `specifications` JSON;
- ao menos **20 pedidos históricos** distribuídos nos últimos 30 dias, com
  status variados (`pendente`, `processado`, `falha`), totais e itens
  coerentes com o catálogo;
- ao menos **10 pagamentos** (aprovados e recusados) e as notificações
  correspondentes;
- ao menos **2 pedidos** pertencentes ao `demo_user` e o restante ao
  `demo_admin`, para exercitar a visibilidade por papel.

Regras:

- usar `get_or_create`/chaves estáveis (`sku` e `idempotency_key`) para que
  duas execuções não dupliquem linhas;
- não apagar dados existentes;
- exigir que `seed_auth` já tenha rodado, com mensagem clara se os usuários
  demo não existirem;
- aceitar `--silent` para uso em scripts;
- ajustar as datas históricas com `update()` (os campos `auto_now_add` não
  aceitam valor no `create`).

### 3.4. Dashboard de vendas

Evoluir o painel principal do Streamlit (`dashboard/app.py` e
`dashboard/queries.py`) para exibir explicitamente indicadores de vendas:

- receita total no período;
- ticket médio;
- receita por dia (gráfico);
- produtos mais vendidos (por quantidade e por receita);
- manter os filtros, a ordenação segura, a paginação/limite e o
  `@st.cache_data(ttl=60)` existentes.

A consulta deve continuar usando SQLAlchemy Core com bind parameters e sem
interpolação de strings. A coluna `itens` (JSON) pode ser lida para agregar
produtos, desde que a consulta continue limitada e segura.

### 3.5. Roteiro de apresentação

Criar `docs/apresentacao/roteiro-demo.md` com:

- pré-requisitos e comandos de subida;
- credenciais demo;
- ordem sugerida da demo (catálogo/cache → pedido → pagamento/notificação →
  IA mock → IA Gemini → dashboards → CI/CD);
- tempo estimado por bloco;
- plano B para cada bloco (por exemplo, `LLM_PROVIDER=mock` se o Gemini
  falhar);
- comandos de diagnóstico (`docker compose ps`, logs dos workers,
  `inspecionar_dlq_kafka`, `validar_mvp.py`).

## 4. Fora de Escopo

- Novos endpoints de negócio ou novos modelos de domínio.
- Automação de deploy real.
- Substituição dos embeddings locais do RAG.
- Testes de carga ou de penetração.

## 5. Testes Exigidos

- `tests/unit/test_seed_demo.py`: idempotência, SKUs válidos, contagens
  mínimas, usuários demo ausentes e `--silent`.
- `tests/unit/test_dashboard_sales.py`: agregações de receita, ticket médio
  e top produtos, incluindo período vazio.
- `tests/integration/test_validar_mvp.py` ou testes unitários do script com
  servidor HTTP falso, cobrindo sucesso, `--skip-ai` e falha.
- A suíte existente deve continuar verde, com cobertura global ≥ 85%.

## 6. Definition of Done

- [ ] `docs/apresentacao/checklist-mvp.md` cobre os dez itens do MVP com
      implementação, teste, evidência e limitações.
- [ ] `scripts/validar_mvp.py` executa todos os passos obrigatórios e falha
      com exit code diferente de zero quando um passo obrigatório falha.
- [ ] `python api/manage.py seed_demo` cria a massa mínima e é idempotente.
- [ ] O painel Streamlit exibe receita total, ticket médio, receita por dia
      e produtos mais vendidos.
- [ ] `docs/apresentacao/roteiro-demo.md` permite conduzir a apresentação sem
      consultar o código.
- [ ] Testes novos e existentes verdes; `ruff check .` e `mypy api services`
      sem novos erros.
- [ ] `README.md`, `docs/CHANGELOG.md` e `PROMPTS.md` atualizados.
- [ ] Nenhuma funcionalidade além das descritas nesta spec foi adicionada.
