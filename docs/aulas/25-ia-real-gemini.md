# Aula 25 — IA real com Google Gemini

Este documento descreve o adaptador Gemini e a política de seleção dos três
recursos de IA do SynapseShop:

- `POST /api/v1/assist/` — assistente de suporte;
- `POST /api/v1/ask_sql/` — texto-para-SQL;
- `POST /api/v1/ask_docs/` — assistente de documentação (RAG).

O padrão é `LLM_PROVIDER=auto`: o Gemini é tentado primeiro e, se estiver
tecnicamente indisponível, o mock especializado da tarefa assume. O mock
continua sendo o padrão explícito de testes/CI e pode ser forçado com
`LLM_PROVIDER=mock`.

## Arquitetura

```
View DRF
  └─ criar_llm_service(tarefa=...)
       ├─ LlmService (timeout, retry+backoff+jitter, circuit breaker, métricas)
       │    ├─ ProvedorLlm primário (Gemini ou mock)
       │    └─ fallback mock task-specific (somente em `auto`)
       └─ seleção por LLM_PROVIDER=auto|gemini|mock
```

Decisões:

- **A resiliência não muda.** `ProvedorGemini` só traduz a porta
  `ProvedorLlm` para o SDK; retry, timeout, breaker e métricas continuam em
  `LlmService`.
- **`auto` é o padrão.** Gemini é o primário; o mock da tarefa é o fallback.
  `gemini` é estrito (sem fallback) e `mock` é determinístico.
- **Fallback só para indisponibilidade técnica.** Timeout, conexão/DNS, 429,
  5xx, circuito aberto, credencial/modelo inválidos e resposta vazia/malformada
  podem cair para o mock. Erro 400 e bloqueio de segurança **não**.
- **Fallback depois da resiliência.** Erros recuperáveis só caem para o mock
  depois de esgotar retry/breaker; erros terminais de disponibilidade
  (401/403/404) caem após a primeira falha.
- **Singleton e breaker por tarefa.** `assist`, `sql` e `docs` têm circuit
  breakers independentes, para que uma falha em SQL não derrube o assistente.
  O mock de fallback não compartilha o breaker do Gemini.
- **Import tardio do SDK.** Quem roda apenas com `LLM_PROVIDER=mock` não
  carrega o cliente HTTP do Google.
- **Cliente injetável.** A suíte usa dublês e nunca toca a rede.
- **Contexto do RAG é dado, não instrução.** As regras ficam no `system` e o
  contexto recuperado vai na mensagem `user`; o modelo é instruído a ignorar
  comandos contidos nos documentos (defesa contra prompt injection).
- **Bloqueio é resposta inválida.** O adaptador lê `finish_reason` e
  `prompt_feedback.block_reason`; conteúdo bloqueado vira `RespostaInvalida`
  (HTTP 502), mesmo que o provedor devolva texto parcial.

## Configuração

No `.env` (gitignored):

```env
LLM_PROVIDER=auto
GEMINI_API_KEY=sua-chave-do-google-ai-studio
LLM_MODEL=gemini-3.5-flash-lite
LLM_MODEL_SQL=gemini-3.5-flash-lite
LLM_MODEL_DOCS=gemini-3.5-flash-lite
LLM_THINKING_BUDGET=
LLM_TIMEOUT_SEGUNDOS=30.0
LLM_MAX_TENTATIVAS=2
LLM_BACKOFF_BASE_SEGUNDOS=0.5
LLM_REDACAO_ATIVA=true
```

Modos:

- `auto` (padrão): Gemini primeiro; mock da tarefa se o Gemini estiver
  tecnicamente indisponível.
- `gemini`: estrito, sem fallback; uma falha aparece como erro para
  diagnóstico.
- `mock`: determinístico, sem rede e sem custo; usado pela suíte e pelo CI.

Observações:

- `LLM_MODEL*` pode continuar com os valores históricos `mock`,
  `mock-sql` e `mock-docs`: em `auto`/`gemini`, a fábrica troca esses
  defaults por `gemini-3.5-flash-lite`; no fallback, o rótulo volta a ser `mock*`.
- `LLM_THINKING_BUDGET` vazio **omite** `thinking_config` — obrigatório no
  Flash-Lite, que rejeita `thinking_budget=0` com HTTP 400. Preencha `0` apenas
  se escolher `gemini-3.5-flash` e quiser desligar o raciocínio; valores
  positivos (ex.: `512`) funcionam nos dois modelos.
- `LLM_TIMEOUT_SEGUNDOS` de 20–30 s é mais realista para o provedor externo;
  o prompt de SQL é o maior dos três e foi o que exigiu 30 s na validação. O
  mock responde em milissegundos.
- `LLM_MAX_TENTATIVAS=2` reduz a espera antes do fallback. Com o padrão do
  código (3) e timeout de 30 s, um Gemini fora do ar pode demorar bastante
  antes de o mock assumir.
- O `docker-compose.yml` repassa `GEMINI_API_KEY` para a API e força
  `LLM_PROVIDER=mock` no serviço `tests`, para que a suíte nunca chame a API
  real mesmo que o `.env` esteja configurado para a apresentação.
- A chave nunca é copiada para a imagem, impressa em log ou devolvida por
  endpoint. O `/api/v1/llm/metrics/` mostra provedor configurado, provedor
  efetivo, modelo da tarefa `assist`, o mapa `modelos` e os contadores de
  fallback; nunca a chave.

## Como obter a chave

1. Acesse o Google AI Studio.
2. Crie uma API key em um projeto com a API Generative Language habilitada.
3. Cole o valor **apenas** no `.env` local ou em um secret do ambiente.
4. Reinicie a API: `docker compose up -d api`.

Não versione o `.env` e não cole a chave em issues, prints ou no `PROMPTS.md`.

## Modelos e custos

O padrão do adaptador é `gemini-3.5-flash-lite` para os três pilares
(`assist`, `sql` e `docs`). Ele é o modelo mais rápido e barato da família 3.5
(1.048.576 tokens de entrada, 65.536 de saída) e foi adotado em 2026-11-17
depois de medições com a chave do projeto: respostas curtas aquecidas em
**3,5–4,1 s**, contra 504 `DEADLINE_EXCEEDED` em 30 s do `gemini-3.5-flash` no
mesmo teste de controle.

Os nomes de modelos mudam com o tempo: o `gemini-2.5-flash`, sugerido na
primeira versão desta aula, foi aposentado para chaves novas (HTTP 404), e o
`gemini-3.5-flash` tornou-se instável na validação. Confirme os disponíveis
para a sua chave com `client.models.list()` e ajuste `LLM_MODEL*` se
necessário. A troca de modelo **e** o ajuste de thinking precisam ir juntos —
sem ele, todo `/assist` real devolve 502.

### Thinking

Até 2026-11-16 o adaptador enviava `thinking_config.thinking_budget=0` para
evitar que tokens de raciocínio consumissem `max_output_tokens` no
`gemini-3.5-flash`. O Flash-Lite **rejeita zero** com
**400 `INVALID_ARGUMENT`** (erro terminal, sem fallback para o mock) e já vem
com `thinking_level=minimal` por padrão. Por isso o campo agora é opcional:

| `LLM_THINKING_BUDGET` | Payload enviado | Uso |
| --- | --- | --- |
| vazio (padrão) | nenhum `thinking_config` | Flash-Lite — recomendado |
| `0` | `thinking_config.thinking_budget=0` | somente modelos que aceitam desligar thinking, ex.: `gemini-3.5-flash` |
| `512` | `thinking_config.thinking_budget=512` | opção explícita com orçamento positivo |

Valores negativos ou não inteiros falham na construção com
`LlmConfiguracaoInvalida`. `temperature` continua sendo enviado: a API o aceita
e o ignora nesta geração (assim como `top_p`/`top_k`). O SDK instalado é
`google-genai 1.75.0` e **não conhece `thinking_level`** — usar esse parâmetro
exigiria upgrade de SDK, fora deste incremento.

Os custos por 1M de tokens são configuráveis e usados apenas para a estimativa
em `/api/v1/llm/metrics/`:

```env
LLM_CUSTO_INPUT_POR_1M_TOKENS=0.30
LLM_CUSTO_OUTPUT_POR_1M_TOKENS=2.50
```

Esses são os preços oficiais publicados para o Flash-Lite e os defaults do
`docker-compose.yml`. Confirme os valores vigentes na página oficial de preços
do Google antes de usar a estimativa em uma apresentação. O projeto não faz
cobrança nem controla cota: o limite real é o da conta Google.

### Cota da free tier (por projeto e por modelo)

| Modelo | Limite observado/informado | Data | Origem |
| --- | --- | --- | --- |
| `gemini-3.5-flash` | 20 requisições/dia | 2026-11-16 | HTTP 429 `RESOURCE_EXHAUSTED` medido na chave do projeto |
| `gemini-3.5-flash-lite` | 15 RPM / 500 RPD | 2026-11-17 | limite informado para a chave; confirmar no AI Studio |

A cota é da **conta/projeto da chave** e é **por modelo**, e pode mudar;
confirme os valores vigentes em
[Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) e
em `aistudio.google.com/rate-limit`. Não há endpoint público que devolva os
limites da chave — os números acima são observações datadas, não garantia do
provedor.

Consequências práticas:

- **Testes e CI nunca usam Gemini.** O serviço `tests` fixa
  `LLM_PROVIDER=mock` e o teste de integração injeta `ProvedorMockSql`; a cota
  não afeta a suíte.
- **Avaliação manual:** com 500 RPD, o golden set inteiro (58 itens) cabe em
  uma janela. Use `python scripts/avaliar_ia.py --delay 4` (teto de 15 RPM;
  com a latência real, ~6–8 RPM). O baseline de 2026-11-17 mediu **60,34%**
  geral e **52,08%** no gate (`consulta` + `rag_tecnico`); `rag_tecnico` e
  `/assist` ficaram em 100%. Evidência:
  [`2026-11-17_1800_gemini.md`](../portfolio/evidencias/ia/2026-11-17_1800_gemini.md).
- **Demonstração:** com a cota esgotada, `auto` cai para o mock. Force
  `LLM_PROVIDER=mock` para não gastar as últimas requisições em ensaio.
- **Relatório:** um run que caiu para o mock não deve ser rotulado como
  Gemini; confira `provedor_efetivo`, `fallbacks` e `ultimo_motivo_fallback`
  em `/api/v1/llm/metrics/`.

Evidências:
[`2026-11-16_gemini-indisponivel.md`](../portfolio/evidencias/ia/2026-11-16_gemini-indisponivel.md)
(20/dia no Flash) e
[`2026-11-17_gemini-3.5-flash-lite.md`](../portfolio/evidencias/ia/2026-11-17_gemini-3.5-flash-lite.md)
(medições do Flash-Lite).

## Como testar

### PowerShell

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/auth/token/' `
  -ContentType 'application/json' `
  -Body '{"username":"demo_admin","password":"<senha>"}'

$headers = @{ Authorization = "Bearer $($login.access)" }

Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/assist/' `
  -Headers $headers -ContentType 'application/json' `
  -Body '{"mode":"summarize","logs":"ERROR timeout ao conectar no banco","max_tokens":128}'

Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/ask_sql/' `
  -Headers $headers -ContentType 'application/json' `
  -Body '{"question":"Quantos pedidos existem por status?"}'

Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/ask_docs/' `
  -Headers $headers -ContentType 'application/json' `
  -Body '{"question":"Como rodar os testes?","top_k":3,"min_score":0.25}'
```

### bash/curl

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo_admin","password":"<senha>"}' |
  python -c 'import json,sys; print(json.load(sys.stdin)["access"])')

curl -s -X POST http://localhost:8000/api/v1/ask_docs/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Como rodar os testes?","top_k":3,"min_score":0.25}'
```

O `ask_docs` exige o índice construído:

```bash
docker compose exec api python api/manage.py indexar_docs
```

O smoke automático cobre os três endpoints:

```bash
python scripts/validar_mvp.py
python scripts/validar_mvp.py --skip-ai
```

Com `auto`, o smoke usa Gemini quando a chave está presente. Para validar o
fallback, suba a API com `GEMINI_API_KEY=""` (ou `LLM_PROVIDER=mock`) e
confira em `/api/v1/llm/metrics/` o `provedor_efetivo` e os contadores de
fallback.

## Forçar um modo

```env
# Padrão: Gemini preferencial, mock como fallback técnico
LLM_PROVIDER=auto

# Estrito: falha explícita se o Gemini não responder
LLM_PROVIDER=gemini

# Determinístico: sem rede, sem custo, usado pela suíte/CI
LLM_PROVIDER=mock
LLM_MODEL=mock
LLM_MODEL_SQL=mock-sql
LLM_MODEL_DOCS=mock-docs
LLM_TIMEOUT_SEGUNDOS=5.0
```

```bash
docker compose up -d api
```

## Mapeamento de erros

| Condição do Gemini | Exceção da camada | HTTP em `gemini` | Fallback em `auto`? |
| ------------------ | ----------------- | ---------------- | ------------------- |
| chave ausente/vazia | `LlmConfiguracaoInvalida` | 500 | Sim, na montagem (mock) |
| 401/403 (credencial) | `LlmConfiguracaoInvalida` | 500 | Sim, após a primeira falha |
| 404 (modelo indisponível) | `LlmModeloIndisponivel` | 502 | Sim, após a primeira falha |
| 400 (requisição inválida) | `LlmErroCliente` | 502 | **Não** |
| 429 (rate limit) | `LlmRateLimit` com `retry_after` | 503 após retries | Sim, após o retry |
| 500/502/503/504 | `LlmErroServidor` | 503 após retries | Sim, após o retry |
| timeout de transporte | `LlmTimeout` | 503 | Sim, após o retry |
| falha de conexão/DNS | `LlmConexao` | 503 | Sim, após o retry |
| resposta vazia/malformada | `RespostaInvalida` | 502 | Sim, após o retry |
| bloqueio de segurança | `RespostaBloqueada` | 502 | **Não** |

A política de retry existente decide o que é recuperável; o adaptador não
reimplementa retry. O fallback é acionado pelo `LlmService` depois de esgotar
retry/breaker. Erros terminais de disponibilidade (401/403/404) caem para o
mock após a primeira falha; chave ausente/vazia é tratada na montagem. O
`finish_reason` (`SAFETY`, `RECITATION`, `BLOCKLIST`, `PROHIBITED_CONTENT`,
`SPII` e correlatos) e o `prompt_feedback.block_reason` são verificados antes
do texto: um bloqueio nunca é devolvido como resposta válida nem cai para o
mock.

## Troubleshooting

- **HTTP 500 “camada de IA mal configurada”:** ocorre no modo `gemini`
  estrito quando `GEMINI_API_KEY` está ausente/vazia ou foi rejeitada. Em
  `auto`, a chave ausente cai para o mock com warning. Confira o `.env`,
  reinicie a API e veja o log `core.llm` (a chave não aparece nele).
- **HTTP 502 com `400 INVALID_ARGUMENT` no log:** quase sempre
  `thinking_budget=0` enviado ao Flash-Lite. Deixe `LLM_THINKING_BUDGET` vazio
  e reinicie a API. Erro 400 é terminal e **não** cai para o mock em `auto`.
- **HTTP 429:** cota/rate limit da conta Google. Aguarde o `retry_after` ou
  reduza a frequência; use `--delay 4` no harness e o breaker pode abrir
  temporariamente.
- **HTTP 502 “resposta inválida”:** conteúdo bloqueado por segurança ou
  resposta sem texto. Bloqueio de segurança não faz fallback; reformule o
  prompt e remova dados sensíveis dos logs.
- **HTTP 503:** provedor indisponível, timeout ou circuito aberto e o
  fallback também falhou. Verifique a conectividade do container
  (`docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('https://generativelanguage.googleapis.com', timeout=10).status)"`).
- **Fallback inesperado:** consulte `provedor_efetivo`,
  `ultimo_motivo_fallback` e `fallbacks` em `/api/v1/llm/metrics/`. Se o
  motivo for timeout, reduza `LLM_MAX_TENTATIVAS` ou aumente o timeout.
- **Latência alta:** o padrão `gemini-3.5-flash-lite` resolveu o 504 do
  `gemini-3.5-flash` nas medições locais (3,5–4,1 s aquecidos). Mantenha
  `LLM_TIMEOUT_SEGUNDOS=30.0` para o prompt de SQL, o mais longo dos três. Em
  `auto`, `LLM_MAX_TENTATIVAS=2` reduz a espera antes do mock. Acompanhe
  `/api/v1/llm/metrics/`.
- **`ask_docs` com `sources: []`:** guardrail acionado — a pergunta não tem
  chunk acima de `min_score`. Reformule ou reindexe com `indexar_docs`.
- **Modelo indisponível (404):** em `auto`, cai para o mock; em `gemini`,
  confirme o nome em `LLM_MODEL*`. O default seguro é
  `gemini-3.5-flash-lite`.

## Limitações

- **RAG lexical:** os embeddings do índice continuam sendo TF-IDF locais;
  esta aula não introduz embeddings neurais nem banco vetorial externo.
  Sinônimos sem tokens em comum podem não ser recuperados.
- **Custo e rede:** o Gemini real depende de conectividade e consome cota. O
  mock existe justamente para testes determinísticos e para o fallback.
- **Fallback com latência:** em `auto`, o mock só assume depois de esgotar
  retry/breaker; com timeout de 30 s e 3 tentativas, a primeira resposta pode
  demorar. Use `LLM_MAX_TENTATIVAS=2` na demo.
- **Fallback limitado:** bloqueio de segurança e erro 400 são terminais e não
  caem para o mock; nesses casos o erro é devolvido ao cliente.
- **Sem streaming, tools ou agentes:** o escopo é completar texto pela mesma
  porta `ProvedorLlm`.
- **Redação de PII:** continua aplicada antes do envio e na resposta, mas não
  substitui a revisão humana do conteúdo colado na demo.

## Arquivos relacionados

- `api/core/llm/gemini.py` — adaptador;
- `api/core/llm/servico.py` — fábrica e seleção por tarefa;
- `api/core/llm/erros.py` — taxonomia neutra;
- `tests/unit/test_llm_gemini.py` — testes do adaptador e da fábrica;
- `tests/unit/test_llm_fallback.py` — testes do fallback e da elegibilidade;
- `docs/portfolio/evidencias/ia/2026-11-17_gemini-3.5-flash-lite.md` — medições
  da troca de modelo;
- `specs/spec_da_aula_25_gemini.md` — spec normativa.
