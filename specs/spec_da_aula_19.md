# Spec: Conexão Segura, SQL Injection e Painel Streamlit (Aula 19)

## 1. Objetivo

Implementar práticas robustas de segurança no acesso ao banco de dados (conexão segura via SSL/TLS, *pooling*, uso de variáveis de ambiente e consultas parametrizadas para mitigação de SQL Injection) e desenvolver um painel de visualização de dados dinâmico utilizando **Streamlit**, integrado via Docker Compose com suporte a *live reload*.

## 2. Contexto

Avançando no ecossistema do **SynapseShop**, esta aula consolida a camada de infraestrutura transacional e introduz ferramentas analíticas e gerenciais para o time. Em conformidade com a **Diretriz de Desenvolvimento Incremental (SpecDD)** e as regras de restrição de escopo:

* **Incluído nesta Spec:** Configuração segura de conexão com o banco de dados (via SQLAlchemy/PostgreSQL), aplicação estrita de consultas parametrizadas (proibindo interpolação de strings), simulação e mitigação de vulnerabilidades de SQL Injection, criação de painéis analíticos no Streamlit com filtros dinâmicos e cache (`@st.cache_data`), e ajuste do Docker Compose com *bind-mount* para desenvolvimento ágil (*live reload*).
* **Sistema:** Você está operando em um ambiente Windows usando PowerShell. Não use utilidades especificar para o Linux como grep, tail, head, or sed. Use cmdlets nativos do PowerShell pra todas as ações do terminal.
* **Proibido nesta Spec:** Antecipação de fluxos de mensageria avançada (RabbitMQ/Kafka das Aulas 9–11), implementação de RAG avançado (Aula 24) ou o pipeline final de CI/CD (Aulas 22–23).

---

## 3. Tarefas e Responsabilidades

* Definir e validar a arquitetura de segurança de dados, assegurando que todas as credenciais e parâmetros de conexão (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SSLMODE=require`) sejam injetados via variáveis de ambiente (`.env`).
* Estabelecer a diretriz de **Zero Interpolação** para consultas SQL, garantindo que o uso de *bind parameters* (consultas parametrizadas) seja obrigatório em todo o código.
* Configurar o módulo de conexão (`db.py`) utilizando SQLAlchemy, habilitando *pooling*, tempos limite (*timeouts*) e exigência de criptografia SSL/TLS.
* Escrever consultas parametrizadas robustas (ex.: utilizando `ANY`, intervalos de datas e *allow-lists* seguras para ordenação dinâmica via `ORDER BY`).
* Conduzir simulações controladas de tentativas de injeção de código (SQL Injection, ex.: `abc' OR '1'='1`) para certificar o bloqueio efetivo pelo mecanismo de parâmetros.
* Desenvolver o painel interativo utilizando **Streamlit**, implementando componentes nativos como campos de texto (`text_input`), seleções múltiplas (`multiselect`) e filtros por data/status.
* Otimizar o desempenho das consultas e reduzir a sobrecarga no banco de dados através da diretiva `@st.cache_data(ttl=60)`.
* Exibir os resultados de forma clara utilizando tabelas (`st.dataframe`) e gráficos dinâmicos (`st.bar_chart`).
* Atualizar a conteinerização do projeto, criando o `Dockerfile` específico para o painel Streamlit e estruturando o `docker-compose.yml` para orquestrar a aplicação junto à base de dados.
* Configurar o *bind-mount* de diretórios para viabilizar o *live reload*, permitindo que alterações locais no código reflitam instantaneamente no navegador durante o desenvolvimento.

---

## 4. Requisitos de Entrega (Definition of Done)

* [ ] **Conexão Segura Configurada:** O acesso ao banco de dados utiliza parâmetros restritos de ambiente, *pooling*, *timeouts* adequados e suporte ativo a SSL/TLS (`DB_SSLMODE=require`).
* [ ] **Mitigação de SQL Injection:** Consultas em SQL utilizam estritamente parâmetros seguros (*bind parameters*), estando formalmente vedada qualquer forma de interpolação direta de strings em queries.
* [ ] **Painel Streamlit Funcional:** O dashboard em Streamlit foi implementado contendo pelo menos dois filtros dinâmicos (como data e status), exibindo tabelas e gráficos interativos.
* [ ] **Otimização com Cache:** O uso de cache de dados (`@st.cache_data`) foi devidamente aplicado para otimizar o desempenho do painel e proteger a base contra requisições excessivas.
* [ ] **Docker Compose e Live Reload:** O ambiente completo sobe com um único comando (`docker-compose up --build`), com suporte a *bind-mount* para atualização em tempo real de código.
* [ ] **Registro de Prompts:** O arquivo `PROMPTS.md` foi atualizado com o histórico de interações e ajustes realizados com IA generativa nesta aula.
* [ ] **Documentação Técnica Atualizada:** O `README.md` contempla a especificação das variáveis de ambiente, instruções de segurança da conexão, diretrizes de prevenção a SQLi e orientações de execução via Docker Compose.