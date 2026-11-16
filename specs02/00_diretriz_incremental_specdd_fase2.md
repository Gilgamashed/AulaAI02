# META-SPEC — Diretriz de Desenvolvimento Incremental da Fase 2 (Portfólio)

## 1. Objetivo da fase 2

A fase 1 (curso de 25 aulas) está encerrada e congelada na tag
`apresentacao-final`. A fase 2 transforma o MVP aprovado em **peça de
portfólio**: um sistema que um recrutador consegue abrir, testar e avaliar sem
depender de apresentação ao vivo.

A fase termina quando o SynapseShop for demonstrável publicamente,
mensurável, documentado para quem não participou do curso e tecnicamente
defensável em entrevista — sem regredir nada da fase 1.

## 2. Regra de ouro (escopo fechado)

Cada incremento entrega apenas o que a sua spec declara. O backlog em
[`README.md`](README.md) registra intenções; **não autoriza implementação**.
Se uma ideia surgir durante o trabalho, ela entra no backlog com prioridade,
não no código.

## 3. Proibição de antecipação (anti-hallucination)

Mantida da fase 1. É proibido:

- implementar item de outro incremento "de passagem";
- trocar biblioteca, provedor ou arquitetura fora do escopo declarado;
- criar modelos, endpoints, migrations ou variáveis de ambiente que a spec
  ativa não pede;
- refatorar código não tocado pelo incremento, salvo correção de bug
  bloqueante — que deve ser registrada como desvio justificado na spec.

## 4. O que muda em relação à fase 1

| Fase 1 (curso) | Fase 2 (portfólio) |
|---|---|
| Unidade: aula numerada | Unidade: incremento com número, slug e prioridade |
| Prazo: calendário de 25 aulas | Prazo: valor de portfólio e risco |
| DoD: critérios da aula | DoD: entregável demonstrável + evidência versionada |
| Escopo: definido pelo professor | Escopo: documento de preparação + decisões registradas |
| Fim: apresentação ao vivo | Fim: repositório público e demo acessível |
| Rastreabilidade: Aula N | Rastreabilidade: tag base, commit, spec e evidência |

## 5. Fluxo SpecDD da fase 2

1. **Ideia** — registrada no backlog de [`README.md`](README.md).
2. **Spec** — criada a partir de [`_template_fase2_spec.md`](_template_fase2_spec.md).
3. **Revisão de escopo** — confirma o que entra e o que fica fora.
4. **Implementação** — apenas o escopo da spec ativa.
5. **Validação** — gate técnico da seção 7 + testes da spec.
6. **Evidência** — artefato em `docs/portfolio/evidencias/` (seção 8).
7. **Registro** — `docs/CHANGELOG.md`, `PROMPTS.md` e, quando houver rota,
   `docs/openapi.yaml`.
8. **Encerramento** — status `Concluído` no README, com link para a evidência.

## 6. Estrutura obrigatória de uma spec de incremento

Toda spec em `specs02/` usa o nome `<numero>_fase2_spec_<slug>.md` e contém:

1. **Objetivo de portfólio** — por que isso importa para quem avalia.
2. **Contexto e problema** — estado atual, com evidência (arquivo, linha,
   métrica ou relatório).
3. **Escopo** — requisitos detalhados e testáveis.
4. **Fora de escopo** — o que explicitamente não será feito.
5. **Métricas de sucesso e evidências** — números e artefatos esperados.
6. **Testes exigidos** — suíte nova e regressões a cobrir.
7. **Definition of Done** — checklist verificável.
8. **Riscos e rollback** — o que pode dar errado e como desfazer.
9. **Dependências** — incrementos, dados, credenciais ou infraestrutura.

## 7. Legado e não-regressão

O baseline é a tag `apresentacao-final` (commit `c77eb47`). Nenhum incremento
pode:

- reduzir a suíte abaixo de **578 testes** nem a cobertura global abaixo de
  **85%** (baseline real: 90,16%);
- quebrar `ruff check .` ou `mypy api services dashboard`;
- alterar contratos de evento em `docs/contracts/` sem atualizar o código
  correspondente em `api/core/messaging/contracts.py`;
- divergir de `docs/openapi.yaml` (baseline `1.26.0`);
- quebrar `python scripts/validar_mvp.py` ou `python scripts/validar_compose.py`;
- remover ou alterar migrations já aplicadas; migrations novas são aditivas.

Exceção só com justificativa explícita na spec do incremento e aprovação
registrada em `PROMPTS.md`.

## 8. Política de portfólio e evidências

- **Sem segredos.** Nunca versionar `.env`, chaves, tokens ou credenciais reais.
- **Sem PII real.** Dados de demonstração são fictícios e gerados por
  `seed_auth`/`seed_demo`.
- **Toda afirmação tem evidência.** Cada incremento deixa um artefato em
  [`docs/portfolio/evidencias/`](../docs/portfolio/evidencias/README.md):
  relatório JSON, captura de tela, GIF ou log resumido.
- **Números, não adjetivos.** "Melhorou" significa taxa antes/depois medida;
  "rápido" significa p50/p95 com metodologia.
- **Limitações explícitas.** O README de portfólio deve declarar o que o
  projeto não faz (mock de front-end, embeddings lexicais, pagamento simulado).

## 9. Política de IA e custo

- Toda mudança em `/assist`, `/ask_sql` ou `/ask_docs` exige execução do
  golden set da spec `01` e comparação antes/depois.
- `LLM_PROVIDER=mock` continua sendo o modo de testes e CI; chamadas reais são
  medições pontuais, com `--max-questions` e registro de custo/latência.
- A redação de PII (`api/core/llm/redacao.py`) não pode ser desativada por
  conveniência de teste.
- Prompts e decisões de engenharia de prompt ficam em `PROMPTS.md`.
- A chave do provedor nunca é impressa em log, relatório ou evidência.

## 10. Priorização

- **P0** — sem isso o portfólio não é convincente (IA mensurável, demo
  acessível, README de recrutador).
- **P1** — maturidade de engenharia que diferencia sênior de júnior
  (observabilidade, segurança, performance, consistência).
- **P2** — diferenciais que ampliam a narrativa, mas não bloqueiam a entrevista.

Dentro da mesma prioridade, ordem: menor risco de regressão primeiro; maior
dependência por último.

## 11. Definition of Done global da fase 2

- [ ] Todos os incrementos P0 com status `Concluído`.
- [ ] Demo pública acessível, com seed reproduzível e credenciais de teste.
- [ ] README de portfólio com problema, arquitetura, trade-offs, como rodar e
      limitações.
- [ ] Golden set de IA versionado e taxa de sucesso atual publicada.
- [ ] Segurança e performance com evidência datada.
- [ ] Nenhuma regressão da fase 1 no gate técnico.
- [ ] `docs/CHANGELOG.md` e `PROMPTS.md` refletindo a fase 2.

## 12. Encerramento da fase

Quando o DoD global estiver completo, a fase 2 é congelada em uma tag
`portfolio-v1`. A partir dela, novas ideias só entram com um novo ciclo de
meta-spec — o mesmo princípio que encerrou a fase 1.
