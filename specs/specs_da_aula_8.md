Spec: Cache-aside com Redis (Aula 8)

1. Objetivo

Otimizar o desempenho da API através da aplicação do padrão cache-aside utilizando Redis para o catálogo e pedidos. O objetivo central compreende a gestão do tempo de vida dos dados em cache (TTL) e a implementação de estratégias robustas para a sua invalidação.

2. Contexto

No estrito cumprimento da diretriz de desenvolvimento incremental e restrição de escopo (SpecDD), o trabalho desta etapa foca-se exclusivamente nos requisitos de otimização e integração do cache. Sob a regra de proibição de antecipação (Anti-Hallucination Rule), a equipa não deve implementar lógicas de filas de mensageria assíncrona com Kafka ou RabbitMQ, ferramentas cujo desenvolvimento se encontra explicitamente reservado para o bloco das aulas 9 a 11.

3. Tarefas e Responsabilidades

Implementação do Cache-aside: Realizar a instrumentação de um endpoint focado em listagem (ex.: GET /pedidos) e de um endpoint de consulta mais pesada (ex.: GET /pedidos/{id}/detalhes) com a aplicação do padrão cache-aside.

Gestão de Chaves e Expiração: Definir chaves de cache claras, como pedidos:list e pedido:{id}. Atribuir-lhes prazos de validade ou TTL, como um tempo inicial sugerido de 60s para a lista e 300s para a consulta de detalhes.

Estratégia de Invalidação: Desenhar e implementar um mecanismo de invalidação de cache associado a eventos do domínio, como garantir que o evento de PedidoAtualizado resulta na invalidação do respetivo pedido:{id} e, caso seja necessário, na invalidação da lista.

Avaliação de Desempenho: Executar e comparar as medições (latência média, p95 e RPS) antes da introdução do cache e depois da sua implementação. Realizar demonstrações em tempo real de todo o ciclo de procura de dados, compreendendo as fases de miss, preenchimento e hit.

Exposição de Métricas: Recolher a métrica de eficácia do cache, ou hit rate (calculado via total_hits/total_lookups), e expor a mesma por endpoint, quer seja num endpoint dedicado a métricas, quer seja através de registos de logs estruturados.

4. Requisitos de Entrega (Definition of Done)

[ ] O Redis, operando como sistema de cache-aside, foi incluído na orquestração e configuração arquitetural do projeto.

[ ] O padrão cache-aside foi executado com sucesso e encontra-se a funcionar num endpoint de listagem e num de acesso a dados específicos.

[ ] O sistema faz uso correto de nomenclatura de chaves, bem como a definição e respeito pelo tempo de vida dos dados (TTL).

[ ] Foi implementada uma regra operacional para a invalidação do cache baseada em eventos vinculados ao negócio.

[ ] O ficheiro README.md foi devidamente atualizado, documentando as estratégias de invalidação adotadas e registando detalhadamente as melhorias de desempenho obtidas através das medições efetuadas.

[ ] A implementação não violou a diretriz de contexto restrito, não apresentando qualquer placeholder ou configuração pertencente a funcionalidades futuras.