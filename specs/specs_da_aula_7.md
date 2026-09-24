Spec: Autenticação JWT com papéis e throttling (Aula 7)

1. Objetivo

Implementar a autenticação JWT baseada em papéis (roles) e regras de throttling. O objetivo central é estabelecer segurança mínima para a API, aplicar proteção às rotas administrativas e configurar validações de acesso.

2. Contexto

Seguindo a diretriz de desenvolvimento incremental (SpecDD), esta etapa adiciona a camada de acesso seguro à infraestrutura existente, mantendo o escopo rigorosamente fechado. É terminantemente proibido antecipar lógicas de aulas futuras, como o sistema de cache-aside com Redis (Aula 8) ou mensageria com RabbitMQ/Kafka (Aulas 9–11).

3. Tarefas e Responsabilidades

Criar migrações com índices compostos, simular rollback seguro e implementar um repositório com transação e teste de tempo.

Definir os fluxos de autenticação (JWT/Session) e criar as roles "admin" e "user".

Configurar mecanismos de throttling e estabelecer a segurança mínima para a aplicação.

Aplicar permissões nos endpoints críticos da API e habilitar paginação e filtros coerentes.

Montar e atualizar a coleção do Postman contemplando cenários completos de login, sucesso, erro e acesso negado.

4. Requisitos de Entrega (Definition of Done)

[ ] A autenticação JWT está totalmente funcional, possuindo pelo menos dois papéis de usuário distintos (admin e user).

[ ] As proteções para as rotas administrativas estão devidamente criadas e implementadas.

[ ] As regras de throttling e a segurança mínima foram configuradas nos endpoints da API.

[ ] Os endpoints críticos possuem paginação e filtros coerentes habilitados.

[ ] A coleção de testes no Postman foi atualizada com os cenários de sucesso, erro e acesso negado.

[ ] O código gerado não contém placeholders ansiosos ou implementações de funcionalidades que só devem constar em etapas futuras.