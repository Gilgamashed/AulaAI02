# PROMPTS.md

Registro do histórico de uso de IA generativa no projeto SynapseShop.

## Como registrar

Ao usar qualquer ferramenta de IA (assistentes, código, documentação, revisão),
adicione uma entrada com o formato abaixo em ordem cronológica.

```markdown
## [AAAA-MM-DD] Título resumido

- **Ferramenta:** <nome da ferramenta/modelo>
- **Contexto:** <qual spec/tarefa da aula motivou o uso>
- **Prompt:** <o que foi solicitado>
- **Resultado/Decisão:** <o que foi gerado/adotado, ou por que foi rejeitado>
- **Revisão humana:** <o que o time validou/ajustou>
```

Histórico de uso de IA da equipe — complete conforme a metodologia SpecDD for
executada (registrar apenas usos reais durante o desenvolvimento).

## [2026-09-14] Aula 3 — Dockerfile com runtime, usuário não-root e cache

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 3 — geração do `Dockerfile` atendendo a *runtime*,
  usuário não-root e uso de cache, com revisão de camadas.
- **Prompt:** "criar um 'Dockerfile' que atenda aos requisitos de runtime,
  usuário não-root e uso de cache. A cada passo faça comentários à respeito do
  que está sendo feito."
- **Resultado/Decisão:** `Dockerfile` baseado em `python:3.12-slim`, usuário
  não-root `appuser` (`useradd` + `USER`), cache em duas camadas: (1) `COPY
  requirements.txt` antes do código para a instalação virar camada cacheável e
  (2) `--mount=type=cache,target=/root/.cache/pip` (BuildKit) reutilizando
  downloads do pip entre builds. Criados `requirements.txt` (placeholder, sem
  frameworks) e `.dockerignore` (exclui `node_modules`, `.venv`, `.env`,
  diagramas etc.), reduzindo o build context de vários MB para ~48 kB.
  Validação com `docker build`, `docker compose up` e `docker history`.
- **Revisão humana:** validado na sessão; camadas analisadas e aceitas.

## [2026-09-13] Aula 2 — Validação de conteinerização e correção do WSL

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 2 (esqueleto em camadas e conteinerização) —
  atuação como desenvolvedor(a) e DevOps.
- **Prompt:** "Atue como as skills desenvolvedor/devOps me ajudando a fazer as
  especificações da spec da Aula 2."
- **Resultado/Decisão:** Estrutura `api/`, `services/`, `repositories/`,
  `Dockerfile` e `docker-compose.yml` já entregues no commit `ec76eed` foram
  revisadas e validadas conforme os requisitos da spec. O ambiente foi
  levantado com `docker-compose up` (doD atendido): container `synapseshop_app`
  subiu e imprimiu "SynapseShop container iniciado". Para destravar o Docker
  Desktop (erro "WSL needs updating"), o WSL foi atualizado para 2.7.14 via MSI
  oficial do repositório microsoft/WSL com instalação elevada.
- **Revisão humana:** pendente de validação pela squad (revisão do commit e da
  evidência de execução do `docker-compose up`).

## [2026-09-14] Aula 3 — Orquestração API + PostgreSQL e segredos em .env

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 3 — orquestrar a API simultaneamente com o banco
  de dados usando o `docker-compose.yml`, com injeção de variáveis mínimas.
- **Prompt:** "criar/configurar o arquivo docker-compose.yml para orquestrar a
  API simultaneamente com o banco de dados... Estou curioso com a presença da
  senha e usuário no arquivo docker-compose.yml. Isso é boa prática ou é melhor
  passar pra um arquivo .env?"
- **Resultado/Decisão:** `docker-compose.yml` com dois serviços: `api` (build
  do Dockerfile, `DATABASE_URL` injetada, inicia após `db` saudável via
  `depends_on` + `service_healthy`) e `db` (`postgres:16-alpine`, credenciais,
  volume `pgdata` e healthcheck `pg_isready`). Credenciais **não** ficam
  hardcoded: passam para `.env` (gitignored, carregado automaticamente pelo
  Compose) com `.env.example` versionado e interpolação `${VAR:-default}`.
  Validação: `docker compose up`, `ps` com ambos Up, rede interna resolvendo o
  hostname `db` (172.18.0.3) e logs do banco prontos.
- **Revisão humana:** decisão de mover credenciais para `.env` adotada pela
  squad na sessão; container órfão da versão anterior removido.

## [2026-09-14] Aula 3 — Rota /health, healthcheck e documentação de infra

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 3 — implementar a rota `/health` para checagem de
  disponibilidade, analisar os logs de inicialização e registrar a
  documentação de infraestrutura (README) e transparência (PROMPTS).
- **Prompt:** "vamos registrar a documentação de infraestrutura no README.md e
  manter a transparência atualizando o arquivo PROMPTS.md. E já vamos também
  seguir com a implementação da rota /health para checagem de disponibilidade
  e para realizar a análise dos logs de inicialização do sistema."
- **Resultado/Decisão:** criado `api/main.py` com servidor HTTP de **stdlib**
  (`http.server`) expondo `GET /health` → `200 {"status": "ok",
  "service": "synapseshop-api"}` (sem framework, respeitando o escopo da Aula
  3), logando cada requisição e imprimindo o startup. `Dockerfile` passou a
  executar `python -u api/main.py`. `docker-compose.yml` mapeou `8000:8000` e
  ganhou healthcheck da API com `urllib` em `/health`. `README.md` documentado
  (subir/validar/logs/derrubar) e `PROMPTS.md` atualizado. Validação: `curl
  http://localhost:8000/health` (200) e análise dos logs de inicialização.
- **Revisão humana:** escopo do `/health` limitado a "ok" (sem checagem de
  banco nesta fase); commit local sem push nesta etapa.