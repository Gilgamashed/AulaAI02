# Spec: Consulta de Dados em Linguagem Natural / Texto-para-SQL (Aula 21)

## 1. Objetivo
Implementar a funcionalidade de **Texto-para-SQL (`/ask_sql`)**, permitindo que perguntas de negócio em linguagem natural (português) sejam traduzidas dinamicamente em consultas SQL, executadas no banco de dados relacional e visualizadas no painel em Streamlit.

---

## 2. Contexto
Com base no projeto SynapseShop e na diretriz de desenvolvimento incremental (SpecDD), a Aula 21 foca no módulo de consulta de dados de negócio via IA. O serviço recebe uma pergunta em texto livre, constrói o prompt com o contexto do schema do banco de dados (tabelas e colunas), solicita à LLM a geração da query SQL, executa a consulta de forma segura e exibe os resultados tabulares no Streamlit.

---

## 3. Tarefas e Responsabilidades

* **Engenharia de Prompt & Serviço Python (`/ask_sql`):**
  - Desenvolver o endpoint `POST /api/v1/ask_sql` no serviço Python.
  - Mapear o schema do banco de dados (tabelas `usuarios`, `enderecos_entrega`, `pedidos`, `pagamentos` ou equivalentes do domínio) e injetar o contexto DDL/describe no prompt da LLM.
  - Garantir a extração limpa da instrução SQL gerada pela LLM.

* **Camada de Execução e Segurança de Dados:**
  - Garantir a execução segura no PostgreSQL em modo *read-only* ou via *allow-list* de instruções `SELECT` para mitigar mutações indesejadas (`DROP`, `DELETE`, `UPDATE`, `INSERT`).
  - Tratar exceções de sintaxe SQL ou falhas de execução retornando mensagens claras de erro.

* **Interface Visual (Streamlit):**
  - Criar/atualizar a aba de consulta em linguagem natural no painel Streamlit.
  - Disponibilizar campo de texto para a pergunta do usuário.
  - Exibir a query SQL gerada pela IA e a tabela/dataframe contendo o resultado retornado.

* **Documentação & Rastreabilidade:**
  - Registrar no `PROMPTS.md` os templates de prompt utilizados para a conversão Texto-para-SQL.
  - Atualizar o `README.md` com instruções de uso do endpoint e da interface Streamlit.

---

## 4. Requisitos de Entrega (Definition of Done)

- [ ] **Endpoint `/ask_sql` Operacional:**
  - [ ] Recebe um payload JSON no formato: `{"question": "quais usuários fizeram mais pedidos?"}`.
  - [ ] Processa a pergunta junto à LLM utilizando o contexto de schema do banco.
  - [ ] Retorna a resposta contendo a query SQL gerada e o resultado dos dados formatado em JSON.
- [ ] **Interface Streamlit:**
  - [ ] Contém campo de input funcional para digitação da pergunta em linguagem natural.
  - [ ] Exibe em tela o SQL gerado e o resultado da consulta formatado em tabela (`st.dataframe`).
- [ ] **Segurança e Validação:**
  - [ ] Permite apenas a execução de comandos de leitura (`SELECT`).
- [ ] **Testes & Experimentos:**
  - [ ] Validado com perguntas reais de negócio (ex.: *"Quais os 5 últimos usuários cadastrados?"*, *"Qual a soma do valor dos últimos 3 pedidos?"*).
- [ ] **Documentação:**
  - [ ] Prompts e refinamentos registrados no arquivo `PROMPTS.md`.
  - [ ] Instruções atualizadas no `README.md` do repositório.