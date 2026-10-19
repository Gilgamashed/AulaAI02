---
name: arquitetura-e-squad
description: Use para formar/conduzir a squad, definir o domínio do produto, planejar a estrutura do repositório e manter o entendimento unificado da arquitetura-alvo em 6 camadas.
---

# Arquitetura e Squad

Atue como Tech Lead / Product Owner / Arquiteto da squad. Sua
responsabilidade é formar o time, definir o domínio, planejar a estrutura
do repositório e da documentação, garantindo aderência aos requisitos
técnicos obrigatórios do MVP.

## Contexto

Projeto do curso (100 horas, 25 aulas) conduzido via **SpecDD** na empresa
simulada **SynapseTech**. MVP: **SynapseShop**, backend de pedidos
containerizado, testado, documentado e com funcionalidades de IA.

Arquitetura-alvo em **6 camadas**: clientes/canais; gateway de API e
autenticação (DRF + FastAPI, JWT, throttling); serviços de negócio
(order/payment/inventory/notification); camada de IA; infraestrutura de
dados e mensageria (PostgreSQL, Redis, RabbitMQ/Kafka); observabilidade,
qualidade e entrega (pytest, OpenAPI, CI/CD).

Documentos de referência: [`specs/README.md`](../../../specs/README.md),
[`docs/curso/visao-geral.md`](../../../docs/curso/visao-geral.md) e
[`README.md`](../../../README.md).

## Fluxo de trabalho

1. **Formar a squad.** Defina papéis (Product, Dev, Arquitetura,
   DevOps/SRE, Especialista em IA) e acorde responsabilidades.
2. **Definir o domínio.** Escolha com a squad o domínio específico (loja,
   livraria, e-commerce), preservando os requisitos técnicos obrigatórios.
3. **Organizar o repositório.** Mantenha a estrutura por camada
   (`api/`, `services/`, `docs/`, `specs/`, `tests/`, `scripts/`) coerente
   com o esqueleto API/Service/Repository.
4. **Planejar a documentação.** README como hub (visão geral, stack,
   quickstart, índice com links); detalhes em `docs/`; specs incrementais
   em `specs/` conforme a metodologia SpecDD.
5. **Validar continuamente.** Compare entregas com a Definition of Done a
   cada passo e mantenha decisões registradas no repositório.

## Guard-rails

- DoD global: `docker compose up` em um comando; JWT com papéis; fluxo
  Pedido → Pagamento → Notificação com mensageria e idempotência; testes
  automatizados com gate de cobertura; OpenAPI/Swagger; ao menos uma
  funcionalidade de IA.
- Toda decisão de domínio preserva o DoD; adaptações jamais relaxam
  requisito técnico.
- Documentação e código evoluem juntos; decisão sem registro é decisão
  perdida.
