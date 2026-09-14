# Spec: Docker Essencial: Do Básico ao Compose (Aula 3)

## 1. Objetivo
Construir, otimizar e gerenciar ambientes Docker com eficiência e controle[cite: 1]. O objetivo principal é aprimorar a conteinerização introduzida na Aula 2, implementando melhores práticas na criação da imagem e orquestrando múltiplos serviços (API e Banco de Dados) com injeção de variáveis de ambiente mínimas[cite: 1, 3].

## 2. Contexto
Seguindo a diretriz de desenvolvimento incremental (SpecDD), esta etapa foca exclusivamente na evolução da infraestrutura base[cite: 7]. Os alunos utilizarão inteligência artificial para rascunhar e refinar o `Dockerfile`[cite: 1, 3], introduzindo conceitos avançados como *multistage build* e cache de dependências[cite: 1, 3]. Em conformidade com a proibição de antecipação de etapas, a equipe **não** deve configurar frameworks robustos como Django REST Framework ou lógicas avançadas (tais como IA e mensageria) neste momento[cite: 7].

## 3. Tarefas e Responsabilidades
*   **Geração e Revisão do Dockerfile:** Utilizar IA generativa para criar um `Dockerfile` que atenda aos requisitos de *runtime*, usuário não-root e uso de cache[cite: 1, 3]. Em seguida, conduzir uma revisão detalhada e analisar as camadas construídas utilizando o comando `docker history` para otimização[cite: 1, 3].
*   **Orquestração de Serviços:** Criar e configurar o arquivo `docker-compose.yml` para orquestrar a API simultaneamente com o banco de dados[cite: 1, 3].
*   **Monitoramento Básico e Logs:** Implementar e validar a rota `/health` para checagem da disponibilidade e realizar a análise dos logs de inicialização do sistema[cite: 1, 3].
*   **Documentação Contínua:** Registrar a documentação de infraestrutura no `README.md` e manter a transparência das IA's atualizando o arquivo `PROMPTS.md`[cite: 1, 3, 4].

## 4. Requisitos de Entrega (Definition of Done)
- [ ] O `Dockerfile` implementa a arquitetura de *multistage build* e gerencia o cache eficiente de dependências[cite: 1, 3].
- [ ] O contêiner principal do sistema está configurado com as diretrizes de segurança para execução via usuário não-root[cite: 1, 3].
- [ ] O arquivo `docker-compose.yml` foi desenvolvido integrando a API e o Banco de Dados com suas variáveis essenciais[cite: 1, 3].
- [ ] A aplicação conteinerizada expõe com sucesso uma rota `/health` para monitoramento e validação[cite: 1, 3].
- [ ] O arquivo `PROMPTS.md` foi atualizado com os *prompts* utilizados na IA para a criação do Dockerfile e do Compose, incluindo as correções aplicadas[cite: 3, 4].
- [ ] O arquivo `README.md` está atualizado, contendo os procedimentos documentados sobre como subir, derrubar os contêineres e monitorar os logs[cite: 1, 3].
- [ ] É possível inicializar todo o ambiente orquestrado utilizando um único comando (`docker-compose up`)[cite: 2, 4].
- [ ] O escopo do projeto foi mantido estritamente isolado, garantindo que nenhum código correspondente às implementações de Aulas futuras (como banco de dados complexos ou microsserviços) tenha sido escrito precocemente[cite: 7].