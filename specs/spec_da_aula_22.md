# Especificação Técnica: Pipeline de CI/CD com GitHub Actions (Aula 22)

## 1. Objetivo
Esta especificação define os requisitos para a implementação da Integração Contínua (CI) no projeto **SynapseShop**, utilizando o **GitHub Actions**. O objetivo principal é automatizar o fluxo de verificação de código, testes automatizados, análise de estilo/linting e validação do *build* da imagem Docker a cada *commit* ou *pull request*.

---

## 2. Contexto do Projeto e Escopo Incremental (SpecDD)
Alinhado à diretriz de desenvolvimento incremental (SpecDD), esta aula foca exclusivamente no estabelecimento do **pipeline de CI** para validação rápida da aplicação.

> **Atenção:** Etapas avançadas de entrega contínua (CD), tais como *deploy* simulado em produção, publicação de imagem em *registries* remotos (DockerHub/GHCR) e cache de dependências avançado, serão abordadas e estendidas na **Aula 23**.

---

## 3. Tarefas e Responsabilidades
* **DevOps / Engenharia de Software:** 
  * Estruturar a automação no repositório através de workflows em `.github/workflows/ci.yml`.
  * Configurar os *triggers* de execução para escutar novos disparos no branch principal e em *pull requests*.
  * Integrar o ambiente Python, a instalação de dependências e a execução dos testes automatizados com `pytest`.
  * Garantir a validação estática do *build* da imagem Docker para assegurar a integridade dos contêineres.

* **Time de Desenvolvimento / QA:**
  * Assegurar que os testes e a suíte de testes existente executem sem falhas no ambiente de CI.
  * Garantir o tratamento correto de variáveis de ambiente e segredos sensíveis (`SECRET_KEY`, `DB_URL`, etc.) no painel do GitHub.

---

## 4. Estrutura do Workflow de CI (`.github/workflows/ci.yml`)

O pipeline deve contemplar as seguintes fases sequenciais/paralelas organizadas no ficheiro YAML:

1. **Gatilhos de Execução (Triggers):**
   * Disparo em `push` nos branches `main` / `master`.
   * Disparo em `pull_request` direcionado ao branch principal.
   * Suporte a disparo manual via `workflow_dispatch`.

2. **Job de Teste e Linting (`test-and-lint`):**
   * **Runner:** `ubuntu-latest`.
   * **Etapas (Steps):**
     * Checkout do código-fonte (`actions/checkout@v4`).
     * Configuração do runtime Python (`actions/setup-python@v5`).
     * Instalação de dependências do projeto.
     * Verificação de qualidade/estilo de código (ex.: `flake8`, `black --check` ou `ruff`).
     * Execução da suíte de testes com `pytest` e geração de relatórios.

3. **Job de Validação do Build Docker (`docker-build`):**
   * **Runner:** `ubuntu-latest`.
   * **Etapas (Steps):**
     * Checkout do código-fonte.
     * Validação do `Dockerfile` e execução do *build* da imagem localmente (`docker build -t synapseshop-api:test .`).
     * Garantia de que a conteinerização está consistente e sem erros de empacotamento.

---

## 5. Requisitos de Entrega (Definition of Done — DoD)

- [ ] A pasta `.github/workflows/` foi criada contendo o arquivo `ci.yml` devidamente versionado.
- [ ] O pipeline executa com sucesso as etapas de checkout, setup do Python, instalação de dependências e linter.
- [ ] A suíte de testes automatizados (`pytest`) é executada no CI e a compilação do pipeline falha caso algum teste quebre.
- [ ] O processo de *build* do contêiner Docker foi integrado ao pipeline e é validado sem erros a cada execução.
- [ ] As variáveis de ambiente e segredos do projeto foram devidamente abstraídos e configurados no GitHub (`Settings -> Secrets and variables -> Actions`).
- [ ] O arquivo `README.md` foi atualizado com a explicação do pipeline de CI e com o *badge* de status da build do GitHub Actions.
- [ ] O histórico de prompts utilizados com IA generativa para a confecção da especificação e workflows foi registado no `PROMPTS.md`.