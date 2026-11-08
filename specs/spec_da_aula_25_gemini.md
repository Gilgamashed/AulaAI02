# Spec da Aula 25 — Provedor Gemini Real para a Camada de IA

## 1. Objetivo

Adotar o Gemini como provedor preferencial das três funcionalidades de IA do
SynapseShop, com seleção por variável de ambiente e fallback automático para
os provedores mock quando o Gemini estiver **tecnicamente indisponível**,
preservando:

- a porta `ProvedorLlm` e a resiliência existente (timeout, retry com
  backoff + jitter e circuit breaker);
- o mock como padrão explícito de testes e de CI;
- o fallback apenas para indisponibilidade técnica, nunca para bloqueio de
  segurança ou requisição inválida;
- a validação de SQL e a transação read-only;
- o guardrail e a citação de fontes do RAG;
- a redação de PII/segredos antes de qualquer chamada externa.

## 2. Contexto

A camada de IA foi construída na Aula 14 em torno de uma porta única
(`api/core/llm/portas.py`). A fábrica `criar_llm_service` escolhe provedores
especializados por tarefa:

- `assist` → `ProvedorMock`;
- `sql` → `ProvedorMockSql`;
- `docs` → `ProvedorMockDocs`.

O mock é determinístico, sem rede e sem custo; o Gemini é o provedor real. Esta
revisão define `LLM_PROVIDER=auto` como padrão: o Gemini é tentado primeiro e,
se estiver tecnicamente indisponível, o mock especializado da tarefa assume.
Os contratos HTTP de `/assist/`, `/ask_sql/` e `/ask_docs/` não mudam.

## 3. Requisitos Detalhados

### 3.1. Dependência e configuração

- Adicionar `google-genai` ao `requirements.txt`, com faixa de versão
  compatível com Python 3.12.
- Adicionar ao `.env.example`:
  - `GEMINI_API_KEY=` (placeholder vazio, nunca valor real);
  - `LLM_PROVIDER=auto` com comentário explicando `auto|gemini|mock`;
  - `auto` como padrão: Gemini preferencial, mock como fallback de
    indisponibilidade;
  - modelos sugeridos `gemini-3.5-flash` para assist/sql/docs (confirmar os
    modelos disponíveis para a chave; nomes mudam com o tempo);
  - `LLM_TIMEOUT_SEGUNDOS` com orientação de 20–30 s para o provedor real
    (30 s para o prompt de SQL) e 5 s para o mock;
  - custos por 1M de tokens como exemplo configurável.
- Passar `GEMINI_API_KEY`, `LLM_PROVIDER` e modelos no `docker-compose.yml`
  para os serviços `api` e `tests` (os workers não usam IA). O serviço
  `tests` deve continuar fixando `LLM_PROVIDER=mock`.
- A chave nunca deve ser copiada para a imagem, versionada, impressa em log
  ou devolvida por endpoint.

### 3.2. `ProvedorGemini`

Criar `api/core/llm/gemini.py` com uma classe `ProvedorGemini` que cumpra o
protocolo `ProvedorLlm`.

Requisitos:

- receber `api_key`, `modelo`, `timeout_segundos` e, opcionalmente, um
  cliente injetável para testes;
- falhar com `LlmConfiguracaoInvalida` quando a chave estiver ausente ou
  vazia;
- mapear as mensagens da porta para o SDK:
  - mensagens `system` → `system_instruction`;
  - mensagens `user`/`assistant` → `contents`;
- chamar `client.models.generate_content` com:
  - `model=modelo`;
  - `temperature` recebida;
  - `max_output_tokens=max_tokens`;
- devolver `LlmResposta` com:
  - `texto` da resposta;
  - `tokens_prompt` e `tokens_output` de `usage_metadata` quando
    disponíveis;
  - estimativa conservadora quando o provedor não devolver metadados;
- considerar resposta inválida quando:
  - não houver texto;
  - o `finish_reason` indicar bloqueio de segurança ou conteúdo vazio;
- distinguir bloqueio de segurança (`SAFETY`, `BLOCKLIST`,
  `PROHIBITED_CONTENT`, `SPII`, `RECITATION` e correlatos) de resposta
  vazia/malformada, para que o fallback não contorne uma decisão de segurança;
- não logar o conteúdo das mensagens, a chave ou a resposta bruta.

### 3.3. Mapeamento de erros

Traduzir erros do SDK para a taxonomia de `api/core/llm/erros.py`:

| Condição do Gemini | Exceção da camada | Fallback em `auto`? |
| --- | --- | --- |
| 400 (requisição inválida) | `LlmErroCliente` | Não |
| 401/403 (credencial inválida) | `LlmConfiguracaoInvalida` | Sim (indisponibilidade) |
| 404 (modelo indisponível) | `LlmErroCliente` | Sim (indisponibilidade) |
| 429 (rate limit) | `LlmRateLimit` com `retry_after` | Sim, após esgotar o retry |
| 500, 502, 503, 504 | `LlmErroServidor` | Sim, após esgotar o retry |
| timeout de transporte | `LlmTimeout` | Sim, após esgotar o retry |
| falha de conexão/DNS | `LlmConexao` | Sim, após esgotar o retry |
| resposta vazia/malformada | `RespostaInvalida` | Sim, após esgotar o retry |
| bloqueio de segurança | `RespostaInvalida` com motivo de bloqueio | **Não** |

A política de retry existente deve continuar decidindo o que é recuperável; o
adaptador não deve reimplementar retry. O fallback é acionado pelo
`LlmService` somente **depois de esgotar retry e circuit breaker** e apenas
nas linhas marcadas como “Sim”. Erros terminais de disponibilidade
(401/403/404) não são retentados: nesses casos o fallback ocorre após a
primeira falha. Chave ausente/vazia é verificada na montagem, antes de
qualquer chamada. Bloqueio de segurança e requisição inválida são terminais e
nunca caem para o mock.

### 3.4. Fábrica e seleção por tarefa

Evoluir `criar_llm_service` para:

- aceitar `LLM_PROVIDER=auto`, `LLM_PROVIDER=gemini` e
  `LLM_PROVIDER=mock`;
- usar `auto` como padrão quando a variável não existir;
- em `auto`, montar o Gemini como primário e o mock especializado da tarefa
  como fallback; o fallback só é usado depois de esgotar retry/breaker e
  apenas para indisponibilidade técnica (tabela da seção 3.3);
- em `gemini`, manter o modo estrito, sem fallback: falhas continuam
  explícitas para diagnóstico;
- em `mock`, manter o modo estrito, determinístico, sem rede e sem custo;
- continuar rejeitando qualquer outro valor com
  `LlmConfiguracaoInvalida`;
- usar os modelos por tarefa:
  - `LLM_MODEL` para `assist`;
  - `LLM_MODEL_SQL` para `sql`;
  - `LLM_MODEL_DOCS` para `docs`;
- manter singletons e circuit breakers independentes por tarefa; o mock de
  fallback não compartilha o breaker do Gemini;
- instanciar o `ProvedorGemini` com `settings.GEMINI_API_KEY`,
  `settings.LLM_TIMEOUT_SEGUNDOS` e o modelo da tarefa;
- quando `GEMINI_API_KEY` estiver ausente/vazia, `auto` usa o mock com
  warning; `gemini` falha com `LlmConfiguracaoInvalida`.

O plano B manual continua disponível: `LLM_PROVIDER=mock`. Em `auto`, o mock
é o plano B automático e o modo efetivo deve aparecer nas métricas.

### 3.5. Prompts e guardrails

Ajustar os prompts apenas onde necessário para o provedor real:

- `/assist/`: manter os modos `summarize` e `explain`; reforçar que a
  resposta deve ser objetiva e em português.
- `/ask_sql/`: manter a regra de responder **apenas** SQL, sem markdown nem
  cercas de código; a extração existente continua aceitando cercas como
  defesa.
- `/ask_docs/`: manter a regra de responder exclusivamente com o contexto
  recuperado, citar `[1]`, `[2]` e tratar o contexto como **dado**, não como
  instrução (defesa contra prompt injection na documentação).
- Manter `temperature=0.0` para SQL e docs.
- O guardrail do RAG continua antes da chamada ao provedor: sem chunk acima
  de `min_score`, a LLM não é chamada.
- A citação de fontes continua sendo construída a partir da recuperação e
  reforçada por `_garantir_citacao` quando o modelo omitir.

### 3.6. RAG e embeddings

Os embeddings do índice continuam **locais e lexicais** (TF-IDF do projeto).
Esta spec não introduz embeddings neurais nem banco vetorial externo, para
preservar determinismo, custo zero e funcionamento offline.

A limitação deve ficar documentada: sinônimos sem tokens em comum podem não
ser recuperados; um modelo de embeddings Gemini é evolução futura.

### 3.7. Observabilidade e segurança

- `/api/v1/llm/metrics/` deve refletir:
  - `provedor_configurado` (`auto`, `gemini` ou `mock`);
  - `provedor_efetivo` (Gemini ou mock, conforme a última chamada);
  - `modelos` por tarefa (`assist`, `sql`, `docs`);
  - contador de `fallbacks` e `ultimo_motivo_fallback`;
  - indicador `fallback_ativo`.
- Logs de sucesso/falha continuam no logger `core.llm`, sem chave e sem
  conteúdo sensível. Cada fallback gera um warning com o motivo sanitizado.
- A redação de PII/segredos (`LLM_REDACAO_ATIVA=true`) continua aplicada
  antes do provedor e na resposta.
- Erros do provedor devem virar respostas HTTP já mapeadas:
  - 200 quando o Gemini falha e o fallback mock responde com sucesso;
  - 500 para configuração inválida em modo estrito;
  - 502 para resposta inválida ou bloqueio de segurança (sem fallback);
  - 503 para indisponibilidade/circuito aberto quando o fallback também
    falhar.

### 3.8. Documentação

Criar `docs/aulas/25-ia-real-gemini.md` com:

- arquitetura do adaptador;
- configuração do `.env` com `auto|gemini|mock`;
- como funciona o `auto`, quando ocorre o fallback e como forçar
  `gemini`/`mock`;
- como diagnosticar o provedor efetivo e os fallbacks em
  `/api/v1/llm/metrics/`;
- como obter e cadastrar a chave;
- modelos sugeridos e custos;
- como testar os três endpoints;
- como voltar para o mock;
- troubleshooting (chave inválida, cota, latência, modelo indisponível,
  bloqueio de segurança, fallback acionado);
- limitações (RAG lexical, custo, dependência de rede).

Atualizar `README.md`, `docs/CHANGELOG.md`, `PROMPTS.md` e `AGENTS.md`
quando os comandos/variáveis mudarem.

## 4. Fora de Escopo

- Streaming de resposta.
- Function calling, tools ou agentes.
- Embeddings neurais no RAG.
- Fine-tuning.
- Suporte a outros provedores além de Gemini e mock.
- Fallback para qualquer erro: o fallback é restrito à indisponibilidade
  técnica.
- Fallback em bloqueio de segurança ou requisição inválida.

## 5. Testes Exigidos

- `tests/unit/test_llm_gemini.py`:
  - mapeamento de system/user para o cliente;
  - uso de `temperature` e `max_tokens`;
  - tokens a partir de `usage_metadata`;
  - resposta vazia/bloqueada → `RespostaInvalida`;
  - bloqueio de segurança com motivo distinguível de resposta vazia;
  - 400/403/404 → terminal/configuração;
  - 429 → `LlmRateLimit` com `retry_after`;
  - 5xx/timeout/conexão → recuperável;
  - chave ausente → `LlmConfiguracaoInvalida`;
  - a chave não aparece em `str(exceção)` nem em logs.
- `tests/unit/test_llm_fabrica.py` (ou equivalente):
  - `LLM_PROVIDER=mock` mantém os provedores atuais;
  - `LLM_PROVIDER=gemini` instancia `ProvedorGemini` por tarefa, sem
    fallback;
  - `LLM_PROVIDER=auto` é o padrão e usa Gemini quando a chave existe;
  - `LLM_PROVIDER=auto` usa o mock task-specific quando a chave está
    ausente;
  - `LLM_PROVIDER=desconhecido` falha com `LlmConfiguracaoInvalida`.
- `tests/unit/test_llm_fallback.py` (ou equivalente):
  - timeout, conexão, 5xx, 429 e circuito aberto disparam fallback para o
    mock da tarefa **depois** de esgotar retry/breaker;
  - 400 e bloqueio de segurança **não** disparam fallback;
  - o fallback de `sql` usa `ProvedorMockSql`, o de `docs` usa
    `ProvedorMockDocs` e o de `assist` usa `ProvedorMock`;
  - métricas registram `fallbacks`, `ultimo_motivo_fallback` e
    `provedor_efetivo`.
- Testes de integração dos endpoints com serviço falso injetado, sem rede.
- CI continua com `LLM_PROVIDER=mock`; nenhum teste pode chamar a API do
  Gemini.

## 6. Definition of Done

- [ ] `google-genai` instalado e `ProvedorGemini` implementa a porta sem
      alterar a resiliência.
- [ ] `LLM_PROVIDER=auto` é o padrão e funciona para `/assist/`,
      `/ask_sql/` e `/ask_docs/`, usando Gemini primeiro e o mock da tarefa
      quando o Gemini estiver tecnicamente indisponível.
- [ ] `LLM_PROVIDER=gemini` funciona em modo estrito para os três endpoints,
      sem fallback silencioso.
- [ ] `LLM_PROVIDER=mock` preserva todo o comportamento e os testes atuais.
- [ ] Chave ausente: `auto` usa o mock com warning; `gemini` gera erro
      explícito e seguro, sem vazar segredo.
- [ ] Erros do provedor são mapeados para a taxonomia existente e para os
      status HTTP documentados.
- [ ] Fallback ocorre apenas para indisponibilidade técnica, depois de
      esgotar retry/breaker; 400 e bloqueio de segurança não fazem fallback.
- [ ] `/api/v1/llm/metrics/` mostra provedor configurado, provedor efetivo,
      modelos, fallbacks e último motivo.
- [ ] RAG continua citando fontes e aplicando o guardrail antes da LLM.
- [ ] `docs/aulas/25-ia-real-gemini.md` permite configurar, testar e
      diagnosticar o provedor e o fallback.
- [ ] `README.md`, `docs/CHANGELOG.md`, `PROMPTS.md`, `.env.example` e
      `docker-compose.yml` atualizados.
- [ ] Suíte completa, cobertura ≥ 85%, `ruff check .` e `mypy api services`
      verdes.
- [ ] Nenhum teste automatizado depende de rede ou da chave real.
