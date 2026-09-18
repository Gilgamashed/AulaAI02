# Checklist IA-safe — Revisão de Código Gerado por IA

Guia de checagem adotado pela squad na Aula 4 (spec `specs/specs_da_aula_4.md`)
para revisar **todo** código sugerido por IA generativa antes de ser aceito no
repositório. Deve ser aplicado a cada trecho gerado, inclusive em refatorações.

## 1. Escopo e anti-alucinação (SpecDD)

- [ ] A mudança implementa **apenas** itens explícitos na spec da aula atual.
- [ ] Nenhum import ou dependência de aulas futuras (JWT, Redis, FastAPI, filas/mensageria).
- [ ] Nenhum *placeholder* "ansioso" ou rota/estrutura reservada a recursos futuros.

## 2. Imports e dependências

- [ ] Todos os imports existem e são efetivamente usados (sem imports órfãos).
- [ ] Versões pinadas/limitadas adequadas em `requirements.txt`.
- [ ] Nenhuma biblioteca desnecessária adicionada (ex.: framework duplicado).

## 3. Tipagem e camada de dados

- [ ] Campos usam tipos adequados (DecimalField p/ moeda, PositiveIntegerField p/
      quantidades, JSONField p/ especificações, SlugField p/ URL).
- [ ] `ForeignKey` com `related_name`, `on_delete` e intenção explícitos.
- [ ] Validações de formato/unicidade aplicadas no modelo (e refletidas no ORM).
- [ ] Migração gerada e versionada corresponde fielmente aos models.

## 4. Validações e payload

- [ ] Validações customizadas cobrem fronteiras: preço negativo, SKU malformado,
      nomes em branco, IDs inexistentes.
- [ ] Payloads de escrita validam tipos/formatos **antes** de persistir.
- [ ] Erros de validação retornam **400** com mensagens claras e acionáveis.

## 5. Verbos e status HTTP

- [ ] `GET` list → 200; `GET` detail → 200; `POST` → 201; `PUT`/`PATCH` → 200;
      `DELETE` → 204.
- [ ] Recurso inexistente → **404**; payload inválido → **400**.
- [ ] Nenhum status code *hardcoded* fora do padrão REST/DRF.

## 6. Segredos e configuração

- [ ] Nenhuma credencial hardcoded; segredos via `.env`/variáveis de ambiente.
- [ ] `.gitignore`/`.dockerignore` protegem `.env` e artefatos Python/build.
- [ ] `SECRET_KEY` e `DEBUG` parametrizados por ambiente.

## 7. Operação e validação

- [ ] Migrações aplicam no fluxo do container (`migrate` no startup).
- [ ] Rotas testadas no ambiente conteinerizado (`/health` + matriz CRUD).
- [ ] Documentação atualizada (`README.md`) e transparência de IA (`PROMPTS.md`).