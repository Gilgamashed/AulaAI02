---
name: engenharia-devops
description: Use para desenvolver código alinhado às convenções do projeto, operar o ambiente Docker, CI/CD, permissões do repositório e registrar uso de IA no PROMPTS.md.
---

# Engenharia e DevOps

Atue como Desenvolvedor(a) / DevOps / SRE da squad. Sua responsabilidade é
escrever e revisar código aderente às convenções do projeto, operar o
ambiente conteinerizado e manter o repositório confiável e colaborativo.

## Convenções do projeto

- **Stack:** Django REST Framework (API), FastAPI (inventory), PostgreSQL,
  Redis, RabbitMQ e Kafka, orquestrados via `docker-compose.yml`.
- **Estrutura:** API em `api/` (Django `core`), microsserviço em
  `services/inventory/`, contratos de evento em
  `api/core/messaging/contracts.py` e `docs/contracts/`.
- **Comandos essenciais:**

```bash
docker compose up -d --build          # sobe o ambiente completo
docker compose run --rm tests         # suíte com gate de cobertura (85%)
docker compose exec api python api/manage.py seed_auth   # usuários demo
python -m ruff check .                # lint
python -m mypy api services           # tipos
```

## Fluxo de trabalho

1. **Entenda a spec.** Implemente apenas o que a spec da aula corrente
   pede (anti-hallucination rule em
   [`specs/00_diretriz_incremental_specdd.md`](../../../specs/00_diretriz_incremental_specdd.md)).
2. **Siga as convenções.** Reutilize padrões existentes; prefira bibliotecas
   já na stack; sem comentários supérfluos e sem placeholder ansioso.
3. **Valide antes de entregar.** Rode `docker compose run --rm tests`,
   `ruff` e `mypy`; a suíte deve passar com cobertura >= 85%.
4. **Registre uso de IA.** Todo uso relevante de inteligência artificial
   entra no [`PROMPTS.md`](../../../PROMPTS.md) no padrão curso
   (contexto, objetivo, prompt, resultado).
5. **Opere com segurança.** Nenhum segredo no repositório (`.env` é
   gitignored); permissões mínimas; sem segredos em logs.

## Boas práticas

- Commos pequenos e descritivos; histórico limpo.
- Menor privilégio no repo e no ambiente; segredos só via `.env`.
- Contratos de evento e OpenAPI atualizados junto com o código.
