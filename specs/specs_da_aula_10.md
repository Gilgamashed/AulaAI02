# Spec: Mensageria Assíncrona com Apache Kafka, Idempotência e DLQ (Aula 10)

## 1. Objetivo

Aprofundar a integração de mensageria assíncrona utilizando Apache Kafka, explorando os benefícios de streams, retenção configurável, múltiplos consumidores, partições para paralelismo e semântica de offset. O objetivo prático é implementar o fluxo ponta a ponta de produção e consumo do evento `PedidoCriado`, garantindo idempotência e tratamento seguro de falhas com filas de mensagens mortas (DLQ).

## 2. Contexto

Este módulo faz parte do bloco das Aulas 9 a 11, focado no processamento assíncrono do fluxo de pedido, pagamento e notificação. Em total conformidade com o desenvolvimento incremental e as regras de restrição de escopo (SpecDD), a implementação desta etapa foca rigorosamente na mensageria com o broker escolhido, não devendo incluir a criação de pipelines CI/CD ou lógicas de RAG que pertencem a aulas futuras.

## 3. Tarefas e Responsabilidades

* **Definição de Contratos:** Desenvolver o contrato da mensagem `PedidoCriado`, garantindo que contenha os campos mínimos necessários e a chave de idempotência (idempotency key).


* **Implementação do Produtor:** Construir o endpoint produtor (por exemplo, `POST/pedidos`) responsável por publicar o evento `PedidoCriado`.


* **Construção do Consumidor (Worker):** Desenvolver um consumer/worker focado em processar a mensagem recebida e persistir o seu resultado.


* **Tratamento de Resiliência e Falhas:** Configurar o mecanismo de idempotência armazenando o dedupe com prazo de validade (TTL) e estruturar o roteamento para a Dead Letter Queue (DLQ) após *N* tentativas falhas.


* **Simulação e Validação:** Executar testes ponta a ponta analisando logs de processamento (criar pedido → publicar → consumir), simular falhas forçadas para validar a reentrega e verificar a correta destinação das mensagens para a DLQ.


* **Coleta de Métricas:** Levantar os tempos de execução, focando na observação dos trade-offs entre mecanismo de dedupe, latência e throughput.



## 4. Requisitos de Entrega (Definition of Done)

* [ ] O contrato estrutural da mensagem `PedidoCriado` foi criado contemplando campos mínimos e a chave de negócio para idempotência.


* [ ] O endpoint produtor foi integrado para publicar o evento `PedidoCriado` na fila/tópico com sucesso.


* [ ] O worker consumidor foi implementado, processando a mensagem com garantia de idempotência e gravando o estado resultante.


* [ ] A reentrega de mensagens falhas e a destinação final para a DLQ foram configuradas e efetivamente validadas mediante simulação de erro.


* [ ] Os logs transacionais e a medição dos tempos de execução (latência e throughput) foram analisados e documentados.


* [ ] O arquivo `README.md` foi atualizado registrando a escolha do broker (Apache Kafka), as configurações do contrato de mensagens, a política de idempotência definida, os parâmetros de reentrega e a estratégia para a DLQ.


* [ ] Nenhuma tecnologia ou funcionalidade alheia à infraestrutura de mensageria (como IA ou Dashboards em Streamlit) foi antecipada no código base.