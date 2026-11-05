# Pipeline de CI/CD Avançado: Cache, Docker Compose e Deploy Simulado (Aula 23)

## Objetivo

Evoluir o workflow da Aula 22 para um pipeline que não apenas testa, mas
**constrói com cache**, **valida a integração real dos serviços** e **publica
uma imagem no DockerHub**. O deploy é simulado: não existe ambiente de
produção, mas o caminho de build → login → push → verificação de digest é o
mesmo de um pipeline de entrega contínua.

```
push / pull_request / workflow_dispatch
        │
        ├── test-and-lint ───── ruff + pytest + cobertura 85% + artefatos
        │                        (cache de pacotes do pip)
        │
        ├── docker-build ────── buildx + cache GHA + load + inspect
        │
        ├── compose-smoke ───── up db/api/dashboard + smoke de comunicação
        │       needs: docker-build
        │
        └── publish ─────────── login DockerHub + build-push + digest
                needs: test-and-lint, docker-build, compose-smoke
                somente push em main/master/dev ou dispatch
```

O job `publish` só executa quando os três anteriores passam (`needs`). Um
teste quebrado, um Dockerfile inválido ou uma integração que não sobe
impedem a publicação — o "bloqueio de deploy" que a spec pede para observar.

## Arquitetura do workflow

Arquivo: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml).

### Gatilhos e concorrência

| Evento | Branches |
| --- | --- |
| `push` | `main`, `master`, `dev` |
| `pull_request` | `main`, `master` |
| `workflow_dispatch` | qualquer branch selecionável na UI |

O bloco `concurrency` agrupa por workflow + ref e cancela **somente** runs
antigos de PR. Um push em `dev` não interrompe uma publicação que já começou
no DockerHub; PRs que recebem novos commits param o run anterior para poupar
minutos de runner.

### Job `test-and-lint`

| Etapa | Comando/ação |
| --- | --- |
| Checkout | `actions/checkout@v4` |
| Python | `actions/setup-python@v5`, versão `3.12` |
| Cache | `cache: pip` + `cache-dependency-path` com os quatro requirements |
| Dependências | `pip install -r requirements-dev.txt` |
| Lint | `python -m ruff check .` |
| Testes | `python -m pytest --junitxml=reports/junit.xml --cov-report=xml:reports/coverage.xml` |
| Relatórios | `actions/upload-artifact@v4` com `reports/` e `htmlcov/` (`if: always()`) |

O cache do `setup-python` é chaveado pelo hash dos arquivos listados em
`cache-dependency-path`. Por isso a lista inclui também os requirements
referenciados por `-r` dentro do `requirements-dev.txt`: hashear apenas o
arquivo de desenvolvimento deixaria de invalidar o cache quando uma
dependência de runtime mudasse.

O gate de cobertura continua em `[tool.pytest.ini_options]`
(`--cov-fail-under=85`); o YAML não reimplementa a regra.

### Job `docker-build`

| Etapa | Comando/ação |
| --- | --- |
| Checkout | `actions/checkout@v4` |
| Buildx | `docker/setup-buildx-action@v3` |
| Build | `docker/build-push-action@v6` com `load: true`, tag `synapseshop-api:test` |
| Cache | `cache-from: type=gha,scope=synapseshop-api` / `cache-to: type=gha,mode=max` |
| Confirmação | `docker image inspect synapseshop-api:test --format '{{.Id}}'` |

O driver `docker-container` criado pelo Buildx é o que permite exportar o
cache para o backend `type=gha`. O `mode=max` é essencial num Dockerfile
multistage: sem ele, só a camada final é cacheada e a instalação do pip no
estágio `builder` é refeita.

O `load: true` carrega a imagem no daemon do runner para o `inspect`
confirmar que ela existe. Não há `push` neste job: o build é validado em
todo push e PR, inclusive nos forks sem acesso a secrets.

### Job `compose-smoke`

Sobe **db + api + dashboard** (o `redis` entra como dependência saudável da
API) e valida a comunicação entre eles:

```bash
docker compose -f docker-compose.yml -f .github/compose.ci.yml \
  up -d --wait --wait-timeout 300 db api dashboard
python scripts/validar_compose.py
```

O `--wait` só devolve sucesso quando todos os healthchecks do Compose
estiverem verdes. O `--wait-timeout 300` evita um job pendurado para sempre
se um serviço entrar em crash loop.

O override [`.github/compose.ci.yml`](../../.github/compose.ci.yml) aponta a
API para a imagem `synapseshop-api:ci` construída no passo anterior e remove
o `build:` herdado com `!reset null`. Resultado: o Compose valida a
orquestração **sem reconstruir a API sem cache**, reaproveitando as camadas
gravadas no backend `type=gha`. O `!reset` exige Docker Compose >= 2.24.4.

O script [`scripts/validar_compose.py`](../../scripts/validar_compose.py)
executa cinco verificações:

| # | Caminho | O que prova |
| --- | --- | --- |
| 1 | host → API (`GET /health`) | API publicada e respondendo |
| 2 | host → dashboard (`GET /_stcore/health`) | painel Streamlit saudável |
| 3 | API → PostgreSQL (`manage.py migrate --check`) | API conecta no banco e as migrações estão aplicadas |
| 4 | dashboard → PostgreSQL (`contar_pedidos()`) | painel conecta no banco com TLS/pooling |
| 5 | dashboard → API (`http://api:8000/health`) | resolução DNS e rede do Compose entre serviços |

Em falha, o script imprime `docker compose ps` e as últimas 120 linhas dos
logs de `db`, `api` e `dashboard`. O job ainda tem um passo de diagnóstico
com `if: failure()` e um `down -v` com `if: always()` para limpar o runner.

Por que não subir Kafka, workers e inventory neste job:

- a spec pede a validação de **base, API e painel**;
- Kafka e workers acrescentam 1–2 minutos e um broker a mais para dar erro
  intermitente, sem cobrir nenhum caminho novo do DoD;
- o inventory é testado pela suíte (repositório falso) e pelo build da sua
  própria imagem, fora do escopo do smoke de integração da API/painel.

### Job `publish` (deploy simulado)

Executa apenas em `push` para `main`/`master`/`dev` ou `workflow_dispatch`,
depois que os três jobs anteriores passam.

| Etapa | Ação |
| --- | --- |
| Guarda de segredos | `DOCKERHUB_USERNAME` e `DOCKERHUB_TOKEN` presentes? |
| Login | `docker/login-action@v3` |
| Metadados | `docker/metadata-action@v5` |
| Push | `docker/build-push-action@v6` com `push: true` e cache GHA |
| Verificação | `docker buildx imagetools inspect <imagem>@<digest>` |
| Resumo | tags e digest no `$GITHUB_STEP_SUMMARY` |

Tags geradas:

| Tag | Quando | Uso |
| --- | --- | --- |
| `sha-<sha completo>` | sempre | rastreabilidade e rollback |
| `dev`, `main`, `master` | push no branch | canal de integração |
| `latest` | apenas no branch padrão (`main`) | consumo genérico |

O `provenance: false` evita um manifesto de proveniência nesta simulação; o
objetivo é provar login, push e pull por tag, não attestations de supply
chain. Num cenário real de produção, a proveniência deve ser mantida.

Se os secrets não existirem, o job emite `::warning::` e marca a publicação
como ignorada no resumo. A escolha mantém PRs e forks verdes; no repositório
oficial, com os dois secrets cadastrados, o push acontece normalmente.

## Configurando os segredos

O `gh` do ambiente pode estar usando um `GITHUB_TOKEN` de PAT sem permissão
para `actions/secrets`. Para cadastrar pela conta autenticada no keyring:

```powershell
$env:GITHUB_TOKEN = $null

gh secret set DOCKERHUB_USERNAME --repo Gilgamashed/AulaAI02 --body "SEU_USUARIO_DOCKERHUB"
gh secret set DOCKERHUB_TOKEN --repo Gilgamashed/AulaAI02

gh secret list --repo Gilgamashed/AulaAI02
```

O segundo comando pergunta o token sem exibi-lo. Crie o token em **DockerHub
→ Account Settings → Security → New Access Token**, com escopo **Read &
Write**. Alternativa: **GitHub → Settings → Secrets and variables → Actions
→ New repository secret**.

O nome do repositório no DockerHub é `<DOCKERHUB_USERNAME>/synapseshop-api`.
Se o namespace ainda não tiver o repositório, o primeiro push o cria (desde
que o token tenha permissão de escrita). Para trocar o nome, ajuste
`IMAGE_NAME` no bloco `env` do workflow.

## Monitorização e governança

### Onde olhar

| O que | Onde |
| --- | --- |
| Status de cada job/etapa | Aba **Actions** → run → job → step |
| Tempo por job e por step | run → job (cada step mostra a duração) |
| Cache hit/miss | log do passo `Construir a imagem da API` (linhas `CACHED` / `importing cache manifest`) |
| Relatórios de teste | artefato `relatorios-testes` (JUnit, coverage.xml, htmlcov) |
| Imagem publicada | resumo do run + DockerHub → Tags |
| Logs do Compose | step `Diagnóstico em caso de falha` |

Para acompanhar pela CLI:

```powershell
gh run list --repo Gilgamashed/AulaAI02 --limit 5
gh run watch --repo Gilgamashed/AulaAI02
gh run view <run-id> --log --repo Gilgamashed/AulaAI02
```

### Status checks e notificações

Em **Settings → Branches → Branch protection rules**, marque como
obrigatórios os jobs `Testes e lint`, `Build da imagem Docker` e
`Integração com Docker Compose`. **Não** marque `Publicação no DockerHub`
como obrigatório em PRs: ele não roda em `pull_request` por desenho.

As notificações de falha seguem as preferências do GitHub (**Settings →
Notifications → Actions**). Para acompanhar um workflow específico, use
**Watch → Custom → Actions** no repositório. Um run vermelho notifica os
watchers; um run cancelado por `concurrency` não é falha.

### Cenários de falha propositada

| Cenário | O que acontece | Como reverter |
| --- | --- | --- |
| YAML inválido | O GitHub não agenda o run e mostra "Invalid workflow file"; nenhum job executa | Corrigir o YAML e dar novo push; o último run válido continua sendo a referência |
| Erro de lint/teste | `test-and-lint` fica vermelho; `docker-build`/`compose-smoke` podem rodar em paralelo; `publish` é **skipped** por `needs` | Corrigir e dar novo push |
| Variável do Postgres ausente no Compose | O `db` sobe com credenciais diferentes ou a API não conecta; `--wait` estoura e o diagnóstico mostra `ps` + logs | Restaurar `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` no job |
| Dockerfile quebrado | `docker-build` (e o build do `compose-smoke`) falham; `publish` não roda | Corrigir o Dockerfile; a imagem anterior continua publicada |
| Segredos do DockerHub ausentes | `publish` emite warning e marca "ignorado"; o run fica verde | Cadastrar `DOCKERHUB_USERNAME` e `DOCKERHUB_TOKEN` |
| Token do DockerHub inválido/sem escrita | O login ou o push falham no `publish`; os jobs anteriores continuam verdes | Gerar novo token com Read & Write e atualizar o secret |

### Diagnóstico do primeiro run real

O primeiro run do job `compose-smoke` falhou no `docker compose up --wait`:

```text
dependency failed to start: container synapseshop_api is unhealthy
```

O passo de diagnóstico (`if: failure()`) mostrou a causa real nos logs da API:

```text
psycopg.OperationalError: connection failed: server does not support SSL,
but SSL was required
```

O banco subia saudável porque o healthcheck usa `pg_isready` (sem TLS), mas o
script `docker/postgres/init-ssl.sh` falhava no primeiro start do volume:

- `openssl req ... -key server.key` **lê** uma chave existente em vez de
  criá-la; no volume novo o arquivo ainda não existia e o comando abortava;
- o `ssl` nunca era ligado e a API, que exige `sslmode=require`, morria no
  `migrate` do entrypoint;
- localmente o bug ficava escondido porque o container do banco já tinha
  certificados de uma execução anterior.

Correções aplicadas (detalhadas no `CHANGELOG`):

1. geração com `-newkey rsa:2048 -keyout ...` (idempotente);
2. certificados em `$PGDATA/certs`, dentro do volume;
3. `docker-entrypoint-wrapper.sh` garante TLS também quando o volume já está
   inicializado e reescreve caminhos antigos;
4. `CMD ["postgres"]` redeclarado no Dockerfile do banco (definir `ENTRYPOINT`
   zera o `CMD` herdado).

Depois da correção, o mesmo caminho do CI foi reproduzido localmente com um
volume novo (`COMPOSE_PROJECT_NAME=aula23ci`) e passou nas 5 verificações.

### Rollback

Não existe ambiente de produção nesta simulação. O mecanismo de rollback é
o mesmo de um deploy real baseado em imagem: **voltar para a tag
`sha-<anterior>`**.

```bash
docker pull <usuario>/synapseshop-api:sha-<sha-anterior>
docker image inspect <usuario>/synapseshop-api:sha-<sha-anterior>
```

Num ambiente real, o orquestrador (Compose, Kubernetes, ECS) apontaria para
essa tag. Como cada push publica uma tag imutável por SHA, o rollback não
depende de reconstruir o código antigo: a imagem já existe no registry.

## Equivalente local

```powershell
# Lint e suíte (no host ou no container de testes)
python -m ruff check .
docker compose run --rm tests

# Build com cache local do BuildKit
docker build -t synapseshop-api:test .

# Smoke do Compose: sobe banco, API e painel e valida a comunicação
docker compose up -d --build --wait db api dashboard
python scripts/validar_compose.py

# Para parar sem apagar dados (NUNCA use `down -v` no ambiente local)
docker compose stop db api dashboard
```

Para reproduzir o caminho do CI (imagem da API pré-construída + override):

```powershell
docker buildx build --load -t synapseshop-api:ci .
docker compose -f docker-compose.yml -f .github/compose.ci.yml up -d --wait db api dashboard
python scripts/validar_compose.py
```

## Evidências esperadas

- `test-and-lint`: suíte verde e cobertura >= 85% (baseline da Aula 21:
  398 testes, 89,64%; o número pode crescer).
- `docker-build`: imagem `synapseshop-api:test` criada.
- `compose-smoke`: 5/5 verificações do `scripts/validar_compose.py`.
- `publish`: digest exibido no resumo e tag `sha-<completo>` visível no
  DockerHub.
- Primeiro run com cache frio é mais lento; os seguintes devem mostrar
  `CACHED` no build e tempos menores de instalação de dependências.

### Resultado observado

| Run | Evento | Resultado |
| --- | --- | --- |
| [41937956794](https://github.com/Gilgamashed/AulaAI02/actions/runs/41937956794) | push `dev` (1º) | `test-and-lint` e `docker-build` verdes; `compose-smoke` vermelho por SSL; `publish` skipped |
| [41940296490](https://github.com/Gilgamashed/AulaAI02/actions/runs/41940296490) | push `dev` (correção) | 4 jobs verdes; imagem publicada com tags `dev` e `sha-04d24b9…` e digest `sha256:1934bc34…` |
| [41940892539](https://github.com/Gilgamashed/AulaAI02/actions/runs/41940892539) | PR #15 (drill) | `test-and-lint` vermelho no lint, `compose-smoke` verde, `publish` skipped |

O drill do PR #15 foi fechado sem merge, com a branch apagada. Ele prova o
bloqueio: o job de publicação tem `needs` dos três anteriores e o GitHub não
o agenda quando qualquer dependência falha.

## Limitações registradas

- **Deploy simulado:** o push no DockerHub não provisiona um ambiente. Não
  há blue/green, healthcheck pós-deploy nem tráfego real.
- **Somente a imagem da API é publicada.** Dashboard, inventory e banco são
  construídos no Compose, mas não entram no registry nesta aula.
- **Sem matrix de Python/OS:** o CI valida apenas Python 3.12 em
  `ubuntu-latest`, a mesma versão da imagem de produção.
- **Kafka fora do smoke:** o job de integração não sobe broker nem workers,
  porque o caminho exercitado é o da API/painel com o banco.
- **Cache do DockerHub anônimo:** os pulls de imagens base (`python:3.12-slim`,
  `postgres:16-alpine`) estão sujeitos ao rate limit anônimo do DockerHub;
  o login do job `publish` não é reaproveitado pelos jobs de build.
