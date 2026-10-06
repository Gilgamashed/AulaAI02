# Spec: Desafio Mão na Massa — Núcleo do Mini-Backend (Aula 11)

## 1. Objetivo

Construir e entregar o núcleo funcional de um mini-backend de pedidos para uma loja, garantindo um fluxo mínimo de negócio: criar um pedido, simular um pagamento e notificar. A solução deve ser executada em contentores e integrar nativamente sistemas de cache e mensageria.

## 2. Contexto

Após o estudo teórico e prático sobre cache e filas de mensagens nas aulas anteriores, o objetivo desta aula é aplicar os conhecimentos num desafio prático de consolidação. Em conformidade com a diretriz restrita do desenvolvimento iterativo (SpecDD), as equipas não devem antecipar a criação de testes automatizados completos ou pipelines de CI/CD (temas das aulas subsequentes), focando-se exclusivamente na orquestração dos serviços já definidos para esta etapa. O sistema construído nesta aula será reaproveitado futuramente para a extração de dados e criação de *dashboards*.

## 3. Tarefas e Responsabilidades

* **Implementação da API:** Desenvolver as rotas necessárias para a criação de pedidos e para a simulação do respetivo pagamento.


* **Orquestração de Contentores:** Configurar o `docker-compose` para garantir que a aplicação e os seus serviços dependentes operam de forma orquestrada e funcional.


* **Integração de Mensageria e Cache:** Estabelecer a comunicação utilizando uma fila de mensageria (Kafka ou RabbitMQ) como peça central do fluxo de eventos, em conjunto com o sistema de cache Redis.


* **Observabilidade Básica e Documentação:** Implementar *healthchecks*, geração de registos (*logs*) e atualizar o ficheiro de documentação.



## 4. Requisitos de Entrega (Definition of Done)

* [ ] O fluxo operacional básico (criar pedido ➔ simular pagamento ➔ notificar) foi implementado e testado com sucesso.


* [ ] A API exposta contém os terminais (endpoints) necessários para gerir pedidos e pagamentos.


* [ ] A arquitetura integra um sistema de mensageria (Kafka ou RabbitMQ) e um sistema de cache (Redis).


* [ ] Todo o ecossistema do mini-backend é orquestrado de forma unificada através do Docker Compose.


* [ ] A solução apresenta registos (*logs*) de funcionamento e possui uma rota de *healthcheck* implementada para monitorização.


* [ ] O ficheiro `README.md` foi devidamente atualizado com as instruções de inicialização e utilização do sistema construído.


* [ ] A implementação respeitou estritamente a diretriz de não antecipação de requisitos (Anti-Hallucination Rule), evitando a inclusão precoce de infraestruturas ou testes reservados para o futuro do MVP.