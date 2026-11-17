# 02 — Texto-para-SQL v2: Validação Estrutural e Cobertura Real

## 1. Objetivo de portfólio

Elevar a taxa de sucesso do `/ask_sql/` em perguntas livres de **baseline
medido na spec `01`** para **≥ 90% nas categorias suportadas**, sem abrir mão
da garantia de somente leitura. O incremento prova que o projeto mede, localiza
a causa e corrige com evidência antes/depois — não com troca de modelo.

## 2. Contexto e problema

O pipeline atual (`api/core/ask_sql/`) usa regex para validar a consulta. A
investigação da spec `01` mostrou falsos negativos em SQL válido:

- `_REFERENCIA_TABELA` (`validacao.py`) trata `FROM created_at` de
  `EXTRACT(YEAR FROM created_at)` como tabela fora da allow-list;
- `_JUNCAO_POR_VIRGULA` bloqueia `FROM core_pedido p, jsonb_array_elements(...)`,
  único caminho para agregar os itens do pedido;
- `PALAVRAS_PROIBIDAS` casa com alias comuns (`owner`, `set`, `into`);
- identificadores entre aspas são rejeitados mesmo quando apontam para a
  allow-list;
- não há reparo: o modelo nunca vê o erro de validação para corrigir;
- o schema do prompt declara `core_pedido.itens` como `jsonb`, mas não
  documenta a estrutura interna (`sku`, `quantidade`, `preco_unitario`,
  `produto_id`), então o modelo inventa chaves;
- o mock (`mock_sql.py`) cobre poucos padrões; com `LLM_PROVIDER=auto` e
  fallback, a experiência degrada para o conjunto da demo.

## 3. Escopo

### 3.1. Validador estrutural com AST

Substituir a validação por regex por parsing com `sqlglot` (dialeto
`postgres`), mantendo a taxonomia de erros (`SqlInvalido`, `SqlProibido`) e a
transação read-only existente.

Adicionar a dependência em `requirements.txt` com pin de série estável
(`sqlglot>=27,<32`; a versão efetiva fica registrada no `docs/CHANGELOG.md`).

Regras obrigatórias no AST:

- exatamente **um** comando, do tipo `SELECT`/`WITH`/`UNION`;
- nenhum nó de DML/DDL (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`,
  `CREATE`, `TRUNCATE`, `MERGE`, `COPY`, `CALL`, `SET`, `EXPLAIN`);
- nenhuma função de sistema (`FUNCOES_PROIBIDAS` + `pg_*`) e nenhuma função de
  escrita (`nextval`, `setval`);
- tabelas apenas da allow-list de `constantes.TABELAS` ou CTEs declaradas;
  funções de tabela permitidas: `jsonb_array_elements`, `jsonb_to_recordset`,
  `unnest`, `generate_series`;
- colunas qualificadas resolvidas por alias → tabela → allow-list; colunas não
  qualificadas válidas se existirem em alguma tabela permitida, em um alias de
  `SELECT` ou na saída de uma CTE;
- `SELECT *` e `tabela.*` continuam proibidos;
- comentários (`--`, `/* */`), múltiplos comandos e literais de dólar
  continuam proibidos;
- identificadores entre aspas são aceitos e normalizados, desde que resolvam
  para a allow-list;
- `LIMIT` obrigatório: ausente → aplica `ASK_SQL_MAX_LINHAS`; acima do teto →
  reduz; `LIMIT ALL` → substitui pelo teto; `OFFSET` preservado;
- o SQL executado é o regenerado pelo AST (`sqlglot`), não o texto bruto do
  modelo.

Rollback: variável `ASK_SQL_VALIDADOR=ast|legado` (padrão `ast`). O validador
legado permanece por um ciclo, coberto por testes, e é removido em incremento
futuro.

### 3.2. Reparo com feedback

Adicionar `ASK_SQL_MAX_REPAROS` (padrão `1`, `0` desativa).

Quando a primeira tentativa falhar em erro elegível, o serviço monta uma nova
chamada com:

1. as mensagens originais;
2. a resposta bruta do modelo (o SQL rejeitado);
3. uma mensagem de sistema com o erro sanitizado e a instrução para devolver
   apenas o SQL corrigido.

Elegíveis: `SqlInvalido` (LIMIT, coluna inexistente), `SqlProibido` por
allow-list/projeção e `ExecucaoSqlFalhou` (coluna/tipo inexistente no banco).

Não elegíveis: `PerguntaNaoSuportada`, DML/DDL, funções de sistema, múltiplos
comandos, comentários, `RespostaBloqueada` e falhas de provedor. Tentativa de
injeção não ganha segunda chance.

Contrato: `meta` do `/ask_sql/` passa a expor `reparos` (inteiro) e
`validador` (`ast`/`legado`). Nenhuma mudança no envelope de sucesso existente.

### 3.3. Cobertura semântica

- Documentar no schema do prompt a estrutura de `core_pedido.itens`:
  `[{"sku": string, "quantidade": int, "preco_unitario": "decimal como texto",
  "produto_id": int}]`, com exemplo de agregação via
  `CROSS JOIN LATERAL jsonb_array_elements(p.itens) AS item` e cast de
  `preco_unitario` para `numeric`.
- Cobrir `EXTRACT`, `date_trunc`, `to_char`, `CURRENT_DATE`, `NOW()` e
  intervalos no prompt e nos exemplos.
- Ampliar `GLOSSARIO` e `RELACIONAMENTOS` para os conceitos que o golden set
  usa: faturamento, ticket médio, itens vendidos, receita por produto, pedidos
  por status, clientes que mais compram.
- Ampliar os exemplos *few-shot* de 2 para pelo menos 12, cobrindo as dez
  categorias do golden set.
- Manter a temperatura `0.0` e o teto de tokens atual.

### 3.4. Paridade do mock

Estender `ProvedorMockSql` para responder, de forma determinística e sem rede,
**≥ 80% dos itens `consulta` do golden set** (não apenas os da demo), incluindo
série temporal, ticket médio, ranking de produtos, itens vendidos, status,
métodos de pagamento e clientes com mais pedidos.

Perguntas fora do domínio continuam devolvendo `NAO_SUPORTADO`. O mock não
precisa cobrir perguntas ambíguas nem texto livre fora dos padrões — o alvo de
90% vale para o Gemini.

### 3.5. Telemetria e observabilidade

- `meta.reparos` e `meta.validador` no contrato do `/ask_sql/`.
- Log `AskSqlReparo` com `tentativa`, `resultado` e categoria do erro, sem
  registrar valores de literais.
- `GET /api/v1/llm/metrics/` inalterado; o relatório da spec `01` já mede
  latência e tokens.

## 4. Fora de escopo

- RAG v2, `/assist`, tool calling, streaming, multi-provedor.
- Novas tabelas, endpoints ou modelos de negócio.
- Introspecção livre do banco ou execução de SQL fora da allow-list.
- Cache de respostas do LLM.
- Deploy, performance de carga, segurança de supply chain.
- Substituir o mock por um dicionário gigante de perguntas decoradas.

## 5. Métricas de sucesso e evidências

| Métrica | Antes | Meta | Como medir |
|---|---|---|---|
| Sucesso em `consulta` (Gemini) | baseline da spec `01` | ≥ 90% | golden set |
| Sucesso em `consulta` (mock) | baseline da spec `01` | ≥ 80% | golden set |
| Falsos negativos do validador | casos da seção 2 | 0 | testes de regressão |
| Violações de segurança | 0 | 0 | testes + revisão do AST |
| p95 de latência | baseline | ≤ +20% | relatório antes/depois |
| Reparos por pergunta | 0 | ≤ 1 (padrão) | `meta.reparos` |

Evidências em `docs/portfolio/evidencias/ia/`:

- relatório `AAAA-MM-DD_HHMM_pos-sql-v2_mock.json` e `.md`;
- relatório `AAAA-MM-DD_HHMM_pos-sql-v2_gemini.json` e `.md` (quando
  disponível);
- comparação antes/depois com as mesmas categorias do baseline.

A medição com Gemini deve respeitar o limite de **20 requisições/dia** da free
tier (ver `docs/aulas/25-ia-real-gemini.md`): use `--max-questions 20` e
compare amostras equivalentes. O mock é a regressão diária e não consome cota.

## 6. Testes exigidos

- `tests/unit/test_ask_sql_validacao_ast.py`: pelo menos 30 casos
  parametrizados — `EXTRACT`, `date_trunc`, JSONB via `CROSS JOIN LATERAL`,
  CTE, subquery, janela, `UNION`, `LIMIT` ausente/acima/`ALL`, `OFFSET`,
  aspas, alias, coluna inexistente, tabela fora da allow-list, DML, DDL,
  função de sistema, comentário, múltiplos comandos e literal de dólar.
- `tests/unit/test_ask_sql_reparo.py`: primeira tentativa inválida e segunda
  válida, erro não elegível sem reparo, limite de reparos, `meta.reparos`,
  provedor esgotado e preservação da categoria de erro.
- `tests/unit/test_ask_sql_mock.py`: novos padrões e recusas.
- `tests/unit/test_ask_sql_schema.py`: consistência da allow-list com os
  models, incluindo a estrutura documentada de `itens`.
- `tests/integration/test_ask_sql_endpoint.py`: contrato com `meta.reparos` e
  `meta.validador`, permissões e erros.
- `tests/integration/test_golden_set_ask_sql.py`: itens `ci_mock` verdes com
  `LLM_PROVIDER=mock`.
- Regressão de segurança: todos os testes de validação existentes continuam
  verdes; nenhum SQL de escrita é executado.
- Suíte global ≥ 578 testes, cobertura ≥ 85%; `ruff check .` e
  `mypy api services dashboard` verdes.

## 7. Definition of Done

- [ ] Validador AST em produção com `ASK_SQL_VALIDADOR=ast` padrão.
- [ ] Reparo com feedback implementado e limitado a 1 tentativa por padrão.
- [ ] Schema do prompt documenta a estrutura de `itens` e as funções de data.
- [ ] Mock cobre ≥ 80% dos itens `consulta` do golden set.
- [ ] Golden set: ≥ 90% (Gemini) e ≥ 80% (mock) nas categorias suportadas,
      com relatórios antes/depois publicados.
- [ ] Zero regressão de segurança e nenhum comando de escrita executável.
- [ ] OpenAPI atualizado (versão `1.27.0`) com `meta.reparos` e `meta.validador`.
- [ ] Testes novos e existentes verdes; cobertura ≥ 85%.
- [ ] `ruff check .` e `mypy api services dashboard` verdes.
- [ ] `docs/CHANGELOG.md`, `PROMPTS.md` e `README.md` atualizados.
- [ ] Nenhuma funcionalidade fora da seção 3 adicionada.

## 8. Riscos e rollback

- **Divergência entre AST e PostgreSQL:** a suíte de 30 casos e o golden set
  cobrem o dialeto usado; `ASK_SQL_VALIDADOR=legado` reverte sem deploy de
  código.
- **Dependência nova:** `sqlglot` é MIT, tipada e sem dependências de runtime
  pesadas; a versão fica pinada e registrada.
- **Custo do reparo:** no máximo uma tentativa adicional; latência e tokens
  entram no relatório; se o p95 estourar +20%, o padrão volta a `0` e o
  incremento registra a decisão.
- **Allow-list divergir dos models:** `test_ask_sql_schema.py` falha alto, como
  já faz hoje.
- **Mock virar dicionário de perguntas:** os padrões são por intenção
  (contagem, ranking, série), não por frase exata; revisão de código no DoD.
- **Rollback:** reverter o commit e a variável `ASK_SQL_VALIDADOR`; nenhuma
  migration é criada.

## 9. Dependências

- Spec `01` concluída (golden set e baseline publicados).
- Stack de pé com `seed_demo --com-inventario` e `indexar_docs`.
- `LLM_PROVIDER=mock` para CI e `auto`/`gemini` para a medição final.
