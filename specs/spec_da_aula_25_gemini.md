# Spec da Aula 25 — Provedor Gemini Real para a Camada de IA

## 1. Objetivo

Substituir os provedores mock das três funcionalidades de IA do SynapseShop
por um provedor real baseado na API do Google Gemini, selecionável por
variável de ambiente, preservando:

- a porta `ProvedorLlm` e a resiliência existente (timeout, retry com
  backoff + jitter e circuit breaker);
- o mock como padrão de testes e de CI;
- a validação de SQL e a transação read-only;
- o guardrail e a citação de fontes do RAG;
- a redação de PII/segredos antes de qualquer chamada externa.

## 2. Contexto

A camada de IA foi construída na Aula 14 em torno de uma porta única
(`api/core/llm/portas.py`). Hoje a fábrica `criar_llm_service` aceita apenas
`LLM_PROVIDER=mock` e escolhe provedores especializados por tarefa:

- `assist` → `ProvedorMock`;
- `sql` → `ProvedorMockSql`;
- `docs` → `ProvedorMockDocs`.

O `.env` local já possui `GEMINI_API_KEY`, mas o `.env.example` não a
documenta e o código não tem adaptador. Esta spec fecha essa lacuna sem
alterar os contratos HTTP de `/assist/`, `/ask_sql/` e `/ask_docs/`.

## 3. Requisitos Detalhados

### 3.1. Dependência e configuração

- Adicionar `google-genai` ao `requirements.txt`, com faixa de versão
  compatível com Python 3.12.
- Adicionar ao `.env.example`:
  - `GEMINI_API_KEY=` (placeholder vazio, nunca valor real);
  - `LLM_PROVIDER=mock` com comentário explicando `mock|gemini`;
  - modelos sugeridos `gemini-2.5-flash` para assist/sql/docs;
  - `LLM_TIMEOUT_SEGUNDOS` com orientação de 15–20 s para o provedor real
    e 5 s para o mock;
  - custos por 1M de tokens como exemplo configurável.
- Passar `GEMINI_API_KEY`, `LLM_PROVIDER` e modelos no `docker-compose.yml`
  para os serviços `api` e `tests` (os workers não usam IA).
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
- não logar o conteúdo das mensagens, a chave ou a resposta bruta.

### 3.3. Mapeamento de erros

Traduzir erros do SDK para a taxonomia de `api/core/llm/erros.py`:

| Condição do Gemini | Exceção da camada |
| --- | --- |
| 400, 403, 404 (modelo/chave inválidos) | `LlmErroCliente` ou `LlmConfiguracaoInvalida` |
| 429 (rate limit) | `LlmRateLimit` com `retry_after` quando disponível |
| 500, 502, 503, 504 | `LlmErroServidor` |
| timeout de transporte | `LlmTimeout` |
| falha de conexão/DNS | `LlmConexao` |
| resposta vazia/bloqueada/malformada | `RespostaInvalida` |

A política de retry existente deve continuar decidindo o que é recuperável;
o adaptador não deve reimplementar retry.

### 3.4. Fábrica e seleção por tarefa

Evoluir `criar_llm_service` para:

- aceitar `LLM_PROVIDER=mock` e `LLM_PROVIDER=gemini`;
- manter `mock` como padrão quando a variável não existir;
- continuar rejeitando qualquer outro valor com
  `LlmConfiguracaoInvalida`;
- usar os modelos por tarefa:
  - `LLM_MODEL` para `assist`;
  - `LLM_MODEL_SQL` para `sql`;
  - `LLM_MODEL_DOCS` para `docs`;
- manter singletons e circuit breakers independentes por tarefa;
- instanciar o `ProvedorGemini` com `settings.GEMINI_API_KEY`,
  `settings.LLM_TIMEOUT_SEGUNDOS` e o modelo da tarefa.

Não haverá fallback automático para mock. A troca é explícita via `.env`,
para que uma falha de configuração não fique silenciosa. O plano B da
apresentação é `LLM_PROVIDER=mock`.

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

- `/api/v1/llm/metrics/` deve refletir `LLM_PROVIDER` e o modelo efetivo.
- Logs de sucesso/falha continuam no logger `core.llm`, sem chave e sem
  conteúdo sensível.
- A redação de PII/segredos (`LLM_REDACAO_ATIVA=true`) continua aplicada
  antes do provedor e na resposta.
- Erros do provedor devem virar respostas HTTP já mapeadas:
  - 500 para configuração inválida;
  - 502 para resposta inválida;
  - 503 para indisponibilidade/circuito aberto.

### 3.8. Documentação

Criar `docs/aulas/25-ia-real-gemini.md` com:

- arquitetura do adaptador;
- configuração do `.env`;
- como obter e cadastrar a chave;
- modelos sugeridos e custos;
- como testar os três endpoints;
- como voltar para o mock;
- troubleshooting (chave inválida, cota, latência, modelo indisponível,
  bloqueio de segurança);
- limitações (RAG lexical, custo, dependência de rede).

Atualizar `README.md`, `docs/CHANGELOG.md`, `PROMPTS.md` e `AGENTS.md`
quando os comandos/variáveis mudarem.

## 4. Fora de Escopo

- Streaming de resposta.
- Function calling, tools ou agentes.
- Embeddings neurais no RAG.
- Fine-tuning.
- Suporte a outros provedores além de Gemini e mock.
- Fallback automático entre provedores.

## 5. Testes Exigidos

- `tests/unit/test_llm_gemini.py`:
  - mapeamento de system/user para o cliente;
  - uso de `temperature` e `max_tokens`;
  - tokens a partir de `usage_metadata`;
  - resposta vazia/bloqueada → `RespostaInvalida`;
  - 400/403/404 → terminal/configuração;
  - 429 → `LlmRateLimit` com `retry_after`;
  - 5xx/timeout/conexão → recuperável;
  - chave ausente → `LlmConfiguracaoInvalida`;
  - a chave não aparece em `str(exceção)` nem em logs.
- `tests/unit/test_llm_fabrica.py` (ou equivalente):
  - `LLM_PROVIDER=mock` mantém os provedores atuais;
  - `LLM_PROVIDER=gemini` instancia `ProvedorGemini` por tarefa;
  - `LLM_PROVIDER=desconhecido` falha com `LlmConfiguracaoInvalida`.
- Testes de integração dos endpoints com serviço falso injetado, sem rede.
- CI continua com `LLM_PROVIDER=mock`; nenhum teste pode chamar a API do
  Gemini.

## 6. Definition of Done

- [ ] `google-genai` instalado e `ProvedorGemini` implementa a porta sem
      alterar a resiliência.
- [ ] `LLM_PROVIDER=gemini` funciona para `/assist/`, `/ask_sql/` e
      `/ask_docs/` com a chave do `.env`.
- [ ] `LLM_PROVIDER=mock` preserva todo o comportamento e os testes atuais.
- [ ] Chave ausente gera erro explícito e seguro, sem vazar segredo.
- [ ] Erros do provedor são mapeados para a taxonomia existente e para os
      status HTTP documentados.
- [ ] RAG continua citando fontes e aplicando o guardrail antes da LLM.
- [ ] `docs/aulas/25-ia-real-gemini.md` permite configurar e testar o
      provedor.
- [ ] `README.md`, `docs/CHANGELOG.md`, `PROMPTS.md`, `.env.example` e
      `docker-compose.yml` atualizados.
- [ ] Suíte completa, cobertura ≥ 85%, `ruff check .` e `mypy api services`
      verdes.
- [ ] Nenhum teste automatizado depende de rede ou da chave real.
