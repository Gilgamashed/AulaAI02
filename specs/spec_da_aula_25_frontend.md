# Spec da Aula 25 — Mock de Front-end para Apresentação

## 1. Objetivo

Disponibilizar um mock de front-end simples, servido pela própria API
Django, para demonstrar o MVP de ponta a ponta durante a apresentação final.

O front-end é uma ferramenta de demonstração: não é um produto de produção,
não introduz framework, build step, CDN, novo container ou CORS.

## 2. Contexto

O SynapseShop é um backend. Todos os fluxos existem via API e via Streamlit,
mas a apresentação precisa de uma interface única que mostre catálogo,
pedido, pagamento, notificação e os assistentes de IA sem exigir Postman ou
`curl`.

A solução escolhida é uma página única servida pelo Django em `GET /app/`,
same-origin, com HTML, CSS e JavaScript inline. Assim:

- o navegador fala com a API sem CORS;
- não há serviço adicional no Compose;
- não há etapa de build;
- o mock funciona offline, sem CDN.

## 3. Requisitos Detalhados

### 3.1. Rota e template

- Expor `GET /app/` em `api/config/urls.py`.
- Implementar a view em `api/core/views.py` (view fina, por exemplo
  `TemplateView`) ou em módulo dedicado, mantendo o padrão do projeto.
- Template em `api/core/templates/core/app.html` (o `APP_DIRS=True` já está
  configurado).
- A rota deve terminar em `/`; `APPEND_SLASH` cobre `/app`.
- O template deve ser autocontido: CSS em `<style>` e JavaScript em
  `<script>`, sem arquivos externos obrigatórios.
- Se houver interpolação do Django, usar `{% verbatim %}` para não colidir
  com as template strings do JavaScript.

### 3.2. Autenticação e sessão

- Formulário de login com usuário e senha, chamando
  `POST /api/v1/auth/token/`.
- Guardar `access` e `refresh` em `sessionStorage` (não em `localStorage`).
- Exibir usuário autenticado e papel (`admin`/`user`), inferido pela
  presença do usuário no grupo admin ou pelas respostas 403 das rotas
  administrativas.
- Renovar o access token automaticamente em `401` usando
  `POST /api/v1/auth/token/refresh/`; se o refresh falhar, limpar a sessão
  e voltar ao login.
- Botão de logout que limpa a sessão.
- Nenhum token, senha ou chave deve ir para `console.log`.

### 3.3. Catálogo

- Listar produtos via `GET /api/v1/items/` com paginação, busca
  (`?search=`), filtro por categoria (`?category=`), `is_active` e
  ordenação (`?ordering=`).
- Exibir nome, marca, modelo, SKU, preço, categoria e estoque lógico
  (`is_active`).
- Permitir adicionar item ao carrinho com quantidade.
- Para usuários autenticados, permitir criar produto
  (`POST /api/v1/items/`).
- Para `admin`, permitir editar (`PATCH`) e excluir (`DELETE`) produtos.
- Carregar categorias via `GET /api/v1/categories/` para o formulário e o
  filtro.
- Tratar erros de validação do DRF exibindo os campos retornados.

### 3.4. Pedido

- Exibir o carrinho com SKU, quantidade e total estimado.
- Enviar `POST /api/v1/pedidos/` com o corpo
  `{"itens": [{"sku": "...", "quantidade": N}]}`.
- Gerar uma `Idempotency-Key` por tentativa de checkout
  (`crypto.randomUUID()` quando disponível) e reutilizá-la ao reenviar o
  mesmo carrinho.
- Exibir a resposta 201 com `id`, `status`, `total` e o bloco `evento`.
- Demonstrar idempotência: um botão "reenviar" deve mostrar 200 com o mesmo
  pedido ou 409 quando a chave for reaproveitada para outro conteúdo.
- Listar pedidos do usuário em `GET /api/v1/pedidos/`; `admin` vê todos.
- Permitir atualizar a lista (polling manual) e mostrar
  `status`, `tentativas` e `motivo_falha`.

### 3.5. Pagamento e notificação

- Para um pedido selecionado, enviar
  `POST /api/v1/pedidos/{id}/pagamento/` com
  `{"metodo": "pix|cartao_credito|boleto", "aprovado": true|false,
  "motivo_recusa": "...", "canal": "email|sms|push"}`.
- Fazer polling de `GET /api/v1/pedidos/{id}/pagamento/` até o status sair
  de `registrado`, com limite de tentativas e intervalo de 1 s.
- Exibir `status`, `valor`, `transacao_id`, `aprovado` e o bloco `evento`.
- Exibir as notificações do pedido via
  `GET /api/v1/notificacoes/?pedido={id}` assim que o worker concluir.
- Exibir mensagem clara quando o pagamento ainda não existir (404).

### 3.6. Assistentes de IA

Criar uma seção "IA" com três abas:

1. **Suporte (`/api/v1/assist/`)**
   - `mode` (`summarize`/`explain`), textarea de logs, `temperature` e
     `max_tokens` opcionais;
   - exibir `answer` e `meta.tokens_prompt`/`meta.tokens_output`.
2. **Texto-para-SQL (`/api/v1/ask_sql/`)**
   - pergunta em português, exemplos clicáveis;
   - exibir o SQL gerado em bloco de código, `columns`, `rows`,
     `row_count`, `truncated` e `meta.modelo`;
   - exibir o `detail` e os `examples` em 422.
3. **Documentação (`/api/v1/ask_docs/`)**
   - pergunta, `top_k` e `min_score`;
   - exibir `answer` e a lista `sources` com `path`, `title`, `range` e
     `score`;
   - exibir claramente a resposta de guardrail com `sources: []`.

As abas 2 e 3 são restritas a `admin`; para `user`, exibir aviso de
permissão em vez de chamar a API.

### 3.7. Operação e dashboards

- Exibir `GET /health` (broker e fluxos), `GET /api/v1/cache/metrics/` e
  `GET /api/v1/llm/metrics/` (admin) em cartões simples.
- Exibir links para:
  - Streamlit principal: `http://<host>:8501`;
  - Swagger: `/docs/`;
  - ReDoc: `/redoc/`;
  - OpenAPI: `/docs/openapi.yaml`.
- Não embutir iframes do Streamlit; abrir em nova aba.

### 3.8. Segurança e robustez

- Nunca usar `innerHTML` com dados vindos da API; usar `textContent` ou
  criar elementos DOM.
- Escapar mensagens de erro antes de exibi-las.
- Não persistir tokens em `localStorage`, cookies ou URL.
- Não exibir a `GEMINI_API_KEY` nem qualquer segredo.
- Timeout de rede explícito no `fetch` (por exemplo, `AbortController`).
- Mensagens em português, com indicação do status HTTP em falhas.
- Layout legível em 1366×768, com contraste adequado para projetor.

### 3.9. Integração opcional com a demo de DLQ

Incluir um checkbox "Simular falha (DLQ)" nas seções de pedido e pagamento.
Quando marcado, enviar `X-Simular-Falha: true` e exibir um aviso de que o
pedido/pagamento será encaminhado à DLQ após a escada de reentrega.

O checkbox só deve aparecer quando a página for servida em ambiente de
desenvolvimento (`DEBUG=True`).

## 4. Fora de Escopo

- Framework SPA (React/Vue), bundler, TypeScript ou npm.
- Novo container, nginx, proxy reverso ou configuração de CORS.
- Cadastro de novos usuários, recuperação de senha ou OAuth.
- Testes automatizados de JavaScript em navegador.
- Substituição das páginas Streamlit.

## 5. Testes Exigidos

- `tests/integration/test_app_frontend.py`:
  - `GET /app/` responde 200 e `text/html`;
  - o HTML contém os pontos de montagem das seções principais (catálogo,
    pedido, pagamento, IA, operação);
  - o template não expõe segredo nem token;
  - a rota não exige autenticação.
- Testes existentes de URL/health continuam verdes.
- Cobertura global ≥ 85%, `ruff check .` e `mypy api services` verdes.

## 6. Definition of Done

- [ ] `GET /app/` responde 200 e o mock carrega sem erros de console.
- [ ] Login, logout e refresh de JWT funcionam para `demo_admin` e
      `demo_user`.
- [ ] Catálogo lista, filtra, busca e permite CRUD conforme o papel.
- [ ] É possível criar pedido, reenviar com a mesma chave e observar a
      idempotência.
- [ ] É possível pagar, acompanhar o worker e ver a notificação na UI.
- [ ] As três abas de IA exibem resposta, SQL/tabela e fontes/guardrail.
- [ ] Cartões de saúde, cache e métricas de IA são exibidos.
- [ ] Nenhum dado da API é injetado via `innerHTML`.
- [ ] Nenhum segredo ou token é logado/exibido.
- [ ] A página é servida same-origin, sem CORS e sem novo serviço.
- [ ] Teste de rota/template, suíte, Ruff e mypy verdes.
- [ ] `README.md`, `docs/CHANGELOG.md` e `PROMPTS.md` atualizados.
