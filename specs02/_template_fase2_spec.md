# Template — Spec de Incremento da Fase 2

> Copie este arquivo para `<numero>_fase2_spec_<slug>.md`, preencha todas as
> seções e registre o incremento no [`README.md`](README.md). Não deixe
> marcadores `TODO` na versão aprovada.

## 1. Objetivo de portfólio

O que este incremento prova para quem avalia o projeto? Uma frase, orientada a
evidência (ex.: "elevar a taxa de sucesso do texto-para-SQL de X% para Y% em
perguntas fora do roteiro").

## 2. Contexto e problema

Estado atual com evidência: caminho de arquivo e linha, comportamento
observado, métrica ou relatório anterior. Se não houver medição, a primeira
tarefa do incremento é produzi-la.

## 3. Escopo

Requisitos numerados e testáveis:

### 3.1. <Área>

- ...

### 3.2. <Área>

- ...

## 4. Fora de escopo

Lista explícita do que não será feito neste incremento, mesmo que pareça
relacionado.

## 5. Métricas de sucesso e evidências

| Métrica | Antes | Meta | Como medir |
|---|---|---|---|
| ... | ... | ... | ... |

Artefatos esperados em `docs/portfolio/evidencias/<area>/`.

## 6. Testes exigidos

- Testes novos (arquivo e comportamento coberto).
- Regressões que precisam continuar verdes.
- Comandos de validação manual reproduzíveis.

## 7. Definition of Done

- [ ] Requisitos da seção 3 implementados.
- [ ] Métricas da seção 5 atingidas e registradas.
- [ ] Testes da seção 6 verdes; suíte global ≥ 578 testes e cobertura ≥ 85%.
- [ ] `ruff check .` e `mypy api services dashboard` verdes.
- [ ] OpenAPI e contratos atualizados, se aplicável.
- [ ] `docs/CHANGELOG.md` e `PROMPTS.md` atualizados.
- [ ] Evidência publicada e link registrado no `README.md` desta pasta.
- [ ] Nenhuma funcionalidade fora da seção 3 adicionada.

## 8. Riscos e rollback

- Risco, probabilidade, impacto e mitigação.
- Como reverter (revert do commit, feature flag, migration reversível).

## 9. Dependências

Incrementos anteriores, dados de seed, credenciais, serviços e ordem de
execução.
