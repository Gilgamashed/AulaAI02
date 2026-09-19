# PROMPTS-TEMPLATE.md

Padrão da squad para acionar ferramentas de IA generativa. Define como
descrever **requisitos, restrições e formatos de saída esperados** de forma
explícita, seguindo a metodologia SpecDD e o checklist de revisão
[IA-SAFE.md](IA-SAFE.md).

## Como usar

1. Copie a seção **Template padronizado** (Parte A) e preencha cada bloco para
   a tarefa em questão.
2. Descreva sempre **modelos de dados, dependências e respostas padrão** com
   campos, tipos e validações explícitos (não deixe a IA inferir).
3. Liste **restrições de escopo** (SpecDD — proibido antecipar aulas futuras).
4. Defina o **formato de saída esperado**: arquivos, estrutura e como validar.
5. Ao receber a resposta da IA, aplique o checklist IA-safe antes de aceitar.
6. Registre o uso real no [PROMPTS.md](PROMPTS.md) (transparência).

---

## Parte A — Template padronizado (copie e preencha)

### 1. Contexto

- **Projeto:** <projeto/repositório>
- **Spec/aula de referência:** <arquivo da spec vigente>
- **Diretório alvo:** <caminho onde o código deve ser criado/alterado>

### 2. Objetivo

<O que deve ser gerado — componente, endpoint, scaffold etc., em 1–3 frases>

### 3. Requisitos técnicos

- **Linguagem/framework:** <ex.: Python 3.12, FastAPI, Pydantic v2>
- **Convenções:** tipagem estática obrigatória; `response_model=` em todos os
  endpoints; docstrings/descrições em PT-BR; segredos via ambiente.
- **Porta/binding:** <ex.: 8001, ASGI via uvicorn>

### 4. Modelos de dados (Pydantic/DTO)

| Modelo | Campo | Tipo | Validação |
| ------ | ----- | ---- | --------- |
| <Model> | <campo> | <tipo> | <min/max/pattern/ge/le…> |

### 5. Dependências

- <função/Classe> injetada via `Depends` — <responsabilidade e reuso>.
- <como a dependência é usada por quais endpoints>.

### 6. Respostas padrão

- **Envelope:** `{status, data, message}` (+ factories `ok()` / `error()`).
- **Matriz de status esperada:** 200 OK · 201 Created · 204 No Content · 400
  (payload inválido) · 404 Not Found · <outros conforme o domínio>.

### 7. Restrições (SpecDD / anti-alucinação)

- Proibido implementar/adicionar dependências de aulas futuras:
  <ex.: banco relacional, autenticação, cache, filas>.
- Nenhum placeholder "ansioso" para recursos fora da spec vigente.
- Imports apenas de bibliotecas autorizadas e efetivamente usadas.

### 8. Formato de saída esperado

- **Arquivos/estrutura:** <lista de arquivos e pastas a criar>.
- **Validação:** <como confirmar — ex.: subir o serviço, `/docs` acessível,
  matriz de status testada via curl>.

### 9. Critérios de aceite (DoD)

- [ ] <critério 1 — ex.: scaffold gerado com modelos Pydantic e respostas padrão>
- [ ] <critério 2 — ex.: tipagem estática validada>
- [ ] <critério 3 — ex.: checklist IA-safe aplicado com conformidade>

---

## Parte B — Exemplo preenchido (item 2 da Aula 5)

**Microsserviço complementar de estoque (`inventory`) em FastAPI** — primeiros
prompts que a squad elaborou e aplicou ao scaffold do serviço. O código
resultante está em `services/inventory/`.

### 1. Contexto

- **Projeto:** SynapseShop (MVP backend de pedidos com IA).
- **Spec/aula de referência:** `specs/specs_da_aula_5.md` (Microserviço
  complementar em FastAPI).
- **Diretório alvo:** `services/inventory/`.

### 2. Objetivo

Gerar o scaffold do microsserviço de inventário em FastAPI, contendo modelos
Pydantic, dependências reutilizáveis e respostas padrão, com tipagem estática e
documentação automática das rotas (`/docs`) funcional.

### 3. Requisitos técnicos

- **Linguagem/framework:** Python 3.12, FastAPI (`>=0.115,<1.0`), Pydantic v2,
  uvicorn (`[standard]`, `>=0.30,<1.0`).
- **Convenções:** tipagem estática em todos os endpoints; `response_model=` em
  toda rota; docstrings e descrições em PT-BR; segredos via variáveis de
  ambiente.
- **Porta/binding:** 8001 (a 8000 é do Django), runtime ASGI via uvicorn.

### 4. Modelos de dados (Pydantic)

| Modelo | Campo | Tipo | Validação |
| ------ | ----- | ---- | --------- |
| `HealthResponse` | `status` | `str` | default `"ok"` |
| `HealthResponse` | `service` | `str` | obrigatório (ex.: `synapseshop-inventory`) |
| `InventoryItemCreate` | `sku` | `str` | pattern `^[A-Z]{2,4}-[A-Z0-9-]+$` (SKU da Aula 4) |
| `InventoryItemCreate` | `name` | `str` | não-vazio (`min_length=1`) |
| `InventoryItemCreate` | `quantity` | `int` | `ge=0` (disponível em estoque) |
| `InventoryItemCreate` | `reserved` | `int` | `ge=0` (quantidade reservada) |
| `InventoryItemCreate` | `reorder_level` | `int` | `ge=0` (nível de reposição) |
| `InventoryItemUpdate` | `name` | `str?` | opcional, não-vazio se presente |
| `InventoryItemUpdate` | `quantity` | `int?` | opcional, `ge=0` se presente |
| `InventoryItemUpdate` | `reserved` | `int?` | opcional, `ge=0` se presente |
| `InventoryItemUpdate` | `reorder_level` | `int?` | opcional, `ge=0` se presente |
| `InventoryItem` | — | — | estende `InventoryItemCreate` (resposta de leitura) |

### 5. Dependências

- `ServiceInfo` (name/version) fornecida por `get_service_info()` e injetada via
  `Depends` — dependência padrão da API, usada na raiz (`GET /`).

### 6. Respostas padrão

- **Envelope:** `ApiResponse[T]` `{status, data, message}` com factories
  `ok()` / `error()`.
- **Matriz de status:** 200 OK · 201 Created · 204 No Content · **400** (payload
  inválido — exige handler customizado, FastAPI padrão devolveria 422) · 404
  Not Found · 409 Conflict (SKU duplicado).

### 7. Restrições (SpecDD / anti-alucinação)

- Proibido banco de dados/modelagem relacional (Aula 6), autenticação JWT
  (Aula 7), Redis/mensageria (Aulas 8–11).
- Persistência de estoque **somente em memória** (exercício das rotas).
- Dependências apenas de `fastapi`, `uvicorn` e `pydantic`; imports usados.

### 8. Formato de saída esperado

- **Estrutura:**
  ```
  services/inventory/
  ├── app/
  │   ├── main.py            # FastAPI app + montagem dos routers
  │   ├── schemas.py         # modelos Pydantic
  │   ├── responses.py       # envelope ApiResponse + factories ok()/error()
  │   ├── dependencies.py    # ServiceInfo via Depends
  │   └── routers/inventory.py  # rotas CRUD tipadas
  ├── Dockerfile             # multistage, não-root, uvicorn na 8001
  ├── requirements.txt
  └── .dockerignore
  ```
- **Validação:** `docker build` + container isolado; `/health` → 200; `/docs`
  acessível (Swagger UI); matriz de status testada via `curl`.

### 9. Critérios de aceite (DoD)

- [x] Scaffold gerado com modelos Pydantic e respostas padrão (`services/inventory/`).
- [x] `/docs` e `/openapi.json` acessíveis (200) no container.
- [x] Handler customizado de 400 para payload inválido (item 4).
- [x] Checklist IA-safe aplicado: sem banco, sem auth, imports usados.
- [x] Uso registrado no `PROMPTS.md` (item 1) e Template versionado (item 6).