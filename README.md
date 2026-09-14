# SynapseShop

Backend de Pedidos com Inteligência Artificial — MVP do projeto da squad.

## Equipe

> Lista provisória — atualizar conforme novos membros entrarem na squad.

| Integrante          | Papel                                            |
| ------------------- | ------------------------------------------------ |
| Caius I O           | Tech Lead / Product Owner / DevOps / SRE / Arquiteto / Desenvolvedor / Especialista em IA |

## Domínio

Loja de departamentos: catálogo de produtos variados, com pedidos gerados e
processados ponta a ponta.

## MVP — Backend de Pedidos com IA

O MVP consiste em um backend capaz de receber pedidos e processar o fluxo
**Pedido → Pagamento → Notificação**, com suporte de inteligência artificial
integrada. Nenhum framework web, banco de dados ou serviço externo é definido
nesta fase inicial; o desenvolvimento segue a metodologia **SpecDD** de forma
iterativa e incremental.

## Arquitetura-alvo (6 camadas)

1. **Clientes/Canais** — pontos de entrada que consomem o backend.
2. **Gateway de API e Autenticação** — DRF + FastAPI, com JWT e *throttling*.
3. **Serviços de Negócio** — `order`, `payment`, `inventory` e `notification`.
4. **Camada de IA** — serviços de inteligência artificial do backend de pedidos.
5. **Infraestrutura de Dados e Mensageria** — PostgreSQL, Redis, RabbitMQ/Kafka.
6. **Observabilidade, Qualidade e Entrega** — Streamlit, pytest, OpenAPI, CI/CD.

### Diagrama (versão inicial)

> Descrição textual provisória (a imagem oficial da arquitetura será adicionada
> quando disponível).

```
Clientes/Canais
      │
      v
Gateway de API + Autenticação (DRF + FastAPI, JWT, throttling)
      │
      v
Serviços de Negócio (order → payment → inventory → notification)
      │
      v
Camada de IA
      │
      v
Infraestrutura de Dados e Mensageria (PostgreSQL, Redis, RabbitMQ/Kafka)
      │
      v
Observabilidade | Qualidade | Entrega (Streamlit, pytest, OpenAPI, CI/CD)
```

## Stack de referência

Docker, Django REST Framework, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Redis.

## Como subir o ambiente

Infraestrutura conteinerizada com Docker Compose (Aula 2/3). O ambiente é
composto por dois serviços:

| Serviço | Imagem            | Função                                               |
| ------- | ----------------- | ---------------------------------------------------- |
| `api`   | build do Dockerfile | API header de disponibilidade na rota `/health` (porta 8000) |
| `db`    | `postgres:16-alpine` | Banco PostgreSQL (volume `pgdata` para persistência) |

### Pré-requisitos

- Docker Desktop (com WSL2) e Docker Compose.
- Arquivo `.env` na raiz com as credenciais do banco (usar `.env.example`
  como referência). O Compose o carrega automaticamente.

### Subir o ambiente

```bash
docker compose up -d --build
```

O serviço `api` só inicia depois que o banco responde com sucesso ao
`healthcheck` (`depends_on` + `service_healthy`).

### Validar a disponibilidade

```bash
curl http://localhost:8000/health
# {"status": "ok", "service": "synapseshop-api"}
```

### Acompanhar os logs

```bash
docker compose logs -f api      # logs do serviço API
docker compose logs -f db       # logs do PostgreSQL (ex.: "database system is ready")
```

### Derrubar o ambiente

```bash
docker compose down             # encerra os containers (mantém o volume pgdata)
docker compose down -v          # encerra e apaga o volume (atenção: apaga os dados)
```

## Referências

- [Histórico de uso de IA generativa](PROMPTS.md)
- [Diretriz SpecDD](specs/)