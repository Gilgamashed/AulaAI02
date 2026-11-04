# Spec: Pipeline de CI/CD Avançado: Cache, Docker Compose e Deploy Simulado (Aula 23)

## 1. Objetivo

Aprofundar o pipeline de integração contínua (CI) e introduzir conceitos de entrega contínua (CD), otimizando os fluxos de trabalho (*workflows*) através de estratégias de cache, orquestração de múltiplos serviços com Docker Compose e simulação de *deploy* automatizado.

## 2. Contexto

Com base nos *workflows* configurados na aula anterior (Aula 22) e utilizando a arquitetura completa do sistema (API, painel Streamlit, base de dados e infraestrutura em contentores), os grupos irão aprimorar a automação para garantir eficiência de *compilação* (*build*), validação integrada de serviços e publicação segura de artefactos.

## 3. Tarefas e Responsabilidades

* **Otimização com Cache de Dependências:** Configurar blocos de cache no ficheiro de configuração do GitHub Actions para reutilizar pacotes Python e camadas Docker já instaladas, reduzindo significativamente o tempo de execução do pipeline.

* **Orquestração de Contentores (Docker Compose):** Integrar etapas no pipeline para validar a subida simultânea e a comunicação correta entre os serviços (base de dados, API e painel) utilizando o Docker Compose.

* **Deploy Simulado (DockerHub):** Implementar as ações oficiais (`docker/login-action` e `docker/build-push-action`) para automatizar o *build* e o envio da imagem do projeto para um repositório no DockerHub, utilizando os segredos (*secrets*) configurados no GitHub.

* **Governança e Monitorização:** Acompanhar os registos (*logs*), analisar os tempos de execução, validar *status checks* e testar cenários de falha propositada (erros de sintaxe ou ausência de variáveis) para compreender o comportamento de *rollback* e notificação.

* **Documentação Contínua:** Registar as decisões técnicas e alterações no ficheiro `README.md` e atualizar o histórico de interações com IA no `PROMPTS.md`.

## 4. Requisitos de Entrega (Definition of Done)

* [ ] O ficheiro de configuração do workflow (`.github/workflows/ci.yml` ou equivalente) foi estendido para incluir o mecanismo de cache de dependências e imagens.

* [ ] O pipeline executa com sucesso a validação e a orquestração dos serviços integrados através do Docker Compose.

* [ ] A etapa de publicação automatizada (*deploy* simulado) encontra-se configurada e operacional para o envio de imagens para o DockerHub.

* [ ] Os segredos necessários (`DOCKERHUB_USERNAME` e `DOCKERHUB_TOKEN`) estão devidamente registados nas definições de segurança do repositório no GitHub.

* [ ] O histórico de prompts utilizados no refinamento da pipeline foi documentado no ficheiro `PROMPTS.md`.

* [ ] O painel do GitHub Actions (*Actions*) valida com sucesso todas as etapas (testes, *lint*, *build* e *compose*) a cada novo *push*.