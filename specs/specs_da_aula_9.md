# Spec: Mensageria Assíncrona e Filas com RabbitMQ/Kafka (Aula 9)

## 1. Objetivo

Implementar a comunicação assíncrona baseada em eventos para o fluxo de pedido, pagamento simulado e notificação. O objetivo central é estabelecer um processamento seguro e resiliente através da publicação e consumo de mensagens, garantindo a idempotência das operações e o tratamento de falhas através de filas de mensagens mortas (DLQ).

## 2. Contexto

Em estrita conformidade com a diretriz de desenvolvimento incremental (SpecDD), esta etapa foca-se apenas na integração da infraestrutura de mensageria. A equipa deve estabelecer o fluxo produtor/consumidor para o evento inicial de criação de pedidos. É expressamente proibido antecipar testes automatizados globais, configurações do pipeline CI/CD ou componentes de inteligência artificial nesta fase.

## 3. Tarefas e Responsabilidades

* **Contratos de Eventos:** Definir estruturalmente a mensagem `PedidoCriado`, que deve conter obrigatoriamente os campos mínimos de negócio e uma chave de idempotência (idempotency key).


* **Implementação do Produtor:** Desenvolver ou adaptar o endpoint da API principal (ex.: `POST /pedidos`) para que publique de imediato o evento `PedidoCriado` na fila de mensagens.


* **Implementação do Consumidor:** Criar um *worker* (serviço consumidor) assíncrono que recolha a mensagem da fila, a processe e persista o estado no repositório.


* **Resiliência e Controlo de Falhas:** Configurar o mecanismo de idempotência através do armazenamento da chave de deduplicação (com prazo de validade/TTL) e estabelecer políticas claras de reentrega e recuo (*backoff*), encaminhando as mensagens repetidamente falhadas para a DLQ após *N* tentativas.


* **Documentação Técnica:** Registrar todas as escolhas de arquitetura sobre o *broker* e as métricas recolhidas.



## 4. Requisitos de Entrega (Definition of Done)

* [ ] O contrato da mensagem `PedidoCriado` foi estabelecido e documentado, contemplando a chave de negócio para garantia de idempotência.


* [ ] O endpoint de criação de pedidos atua corretamente como produtor, publicando eventos no RabbitMQ ou Kafka.


* [ ] O *worker* consome a mensagem `PedidoCriado` com sucesso, garantindo o processamento pelo menos uma vez.


* [ ] A funcionalidade de idempotência está ativa e impede que mensagens idênticas ou duplicadas sejam processadas múltiplas vezes.


* [ ] O fluxo de Dead Letter Queue (DLQ) encontra-se configurado e foi validado através de simulações de erro forçado (reentregas excedidas).


* [ ] Os tempos de execução foram recolhidos, permitindo a análise baseada em *logs*.


* [ ] O ficheiro `README.md` foi atualizado com a justificação da escolha do *broker*, o formato do contrato da mensagem, as regras da política de idempotência, os parâmetros de tentativa de reentrega e a estratégia para a DLQ.


* [ ] Nenhuma antecipação de requisitos (como microsserviços não previstos nesta *spec* ou componentes RAG/IA) foi introduzida no repositório.