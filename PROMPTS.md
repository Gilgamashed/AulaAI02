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