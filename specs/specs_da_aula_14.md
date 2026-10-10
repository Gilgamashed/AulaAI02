Aqui está a especificação (Spec) para a Aula 14, elaborada em português (Portugal) com base nas diretrizes do projeto e no planeamento das aulas:

# Spec: Assistente de IA e llm_service (Aula 14)

## 1. Objetivo

Implementar a camada fundacional de Inteligência Artificial do projeto através da construção do `llm_service` e do endpoint `/api/v1/assist`. O foco incide na resiliência da comunicação com o provedor de LLM, gestão de custos, privacidade de dados e implementação de técnicas iniciais de engenharia de *prompts*.

## 2. Contexto

Seguindo rigorosamente a metodologia de Desenvolvimento Incremental (SpecDD) e a restrição de antecipação, esta iteração concentra-se apenas na infraestrutura do serviço de IA e no primeiro *endpoint* do assistente. A equipa deve considerar cenários do mundo real como falhas de rede, limites de taxa (*rate limits*) da API externa e a proteção de dados sensíveis (LGPD/RGPD) antes de enviar informações para o provedor de LLM.

## 3. Tarefas e Responsabilidades

* **Implementação de Resiliência:** Construir o `llm_service` para comunicar com o provedor de IA, garantindo a configuração de *timeouts* (ex.: ≤5s), políticas de *retry* com *backoff* exponencial mais *jitter* (ex.: 3 tentativas) e um padrão de *circuit breaker* (closed/open/half-open).


* **Desenvolvimento do Endpoint:** Criar o *endpoint* `POST /api/v1/assist` para a sumarização ou explicação de *logs*, controlando os parâmetros de `temperature` e `max_tokens`.


* **Privacidade e Telemetria:** Aplicar técnicas de pseudonimização/ocultação (*redaction*) nos *logs* para evitar a fuga de Informações Pessoais Identificáveis (PII) ou segredos, além de medir a latência, a taxa de erro e o consumo de *tokens*.


* **Garantia de Qualidade:** Escrever testes unitários focados nas margens de erro (cenários de *timeout*, erro 429, erros 5xx e quedas do provedor) utilizando *mocks*.


* **Documentação:** Registar as decisões arquiteturais e políticas de privacidade no `README.md`.



## 4. Requisitos de Entrega (Definition of Done)

* [ ] O `llm_service` foi implementado com mecanismos de *timeout*, *retry* (com *backoff* exponencial) e *circuit breaker*.


* [ ] O *endpoint* `POST /api/v1/assist` está exposto e valida corretamente o seguinte corpo mínimo de requisição: `{ "mode": "summarize|explain", "logs": "string|array", "temperature": 0.0-1.0, "max_tokens": 256 }`.


* [ ] O retorno do *endpoint* segue a estrutura estipulada, devolvendo a resposta gerada e os metadados de consumo: `{ "answer": "...", "meta": { "tokens_prompt": n, "tokens_output": m } }`.


* [ ] Foi implementada telemetria (latência, erros, estimativa de custo por chamada em *tokens*) e os dados sensíveis sofrem *redaction* antes de serem armazenados nos *logs*.


* [ ] A *suite* de testes unitários cobre cenários de exceção e falha do provedor de LLM (*timeout*, HTTP 429, HTTP 5xx, e *payload* inválido).


* [ ] O `README.md` foi atualizado com a arquitetura do `llm_service`, templates de *prompt*, limites configurados, políticas de redação de dados sensíveis e métricas recolhidas.


* [ ] As pendências e potenciais melhorias futuras (ex.: *cache* de respostas ou *guardrails* adicionais) foram registadas como *issues* no repositório.