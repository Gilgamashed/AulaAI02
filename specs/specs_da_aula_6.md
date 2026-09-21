Spec: Modelagem Relacional, Índices e Migrações (Aula 6)

1. Objetivo

O objetivo central da Aula 6 é realizar a modelagem relacional do banco de dados, implementar a definição de índices e gerenciar as migrações do esquema. A infraestrutura de dados será estruturada utilizando PostgreSQL para os dados transacionais, com o mapeamento e migrações orquestrados pelas ferramentas SQLAlchemy e Alembic.

2. Contexto

Seguindo rigorosamente a diretriz de desenvolvimento incremental (SpecDD) e a restrição de escopo do projeto, esta aula concentra-se puramente na camada de persistência de dados. Após as implementações iniciais de roteamento e serviços, a equipe construirá a base transacional do SynapseShop.

Atenção: É estritamente proibido criar placeholders ansiosos ou antecipar configurações de etapas futuras, como a implementação de autenticação JWT com papéis (escopo da Aula 7) ou cache-aside com Redis (escopo da Aula 8).

3. Tarefas e Responsabilidades

Modelagem de Dados:

Discutir e elaborar a modelagem relacional para uma entidade escolhida como base (por exemplo, User, Token ou Pedido).

Integridade e Performance:

Definir os índices essenciais para as consultas.

Estabelecer as regras de integridade do banco de dados relacional.

Gerenciamento de Migrações:

Criar e executar as migrações do banco de dados para aplicar os modelos criados.

Configurar o versionamento do schema de forma segura.

Demonstrar e validar um rollback seguro das migrações aplicadas.

Implementação de Serviços:

Implementar repositórios transacionais.

Desenvolver um serviço que consuma as transações implementadas nesses repositórios.

Validação e Documentação:

Realizar testes transacionais iniciais.

Coletar os tempos de execução das transações.

Registrar formalmente todas as decisões técnicas no repositório do projeto.

4. Requisitos de Entrega (Definition of Done)

[ ] A modelagem relacional de pelo menos uma entidade (ex: User, Token ou Pedido) foi concluída e validada.

[ ] Os índices essenciais foram definidos na modelagem do banco de dados.

[ ] As regras de integridade relacional foram estabelecidas e aplicadas.

[ ] As migrações do banco de dados foram criadas e executadas com sucesso utilizando SQLAlchemy e Alembic no PostgreSQL.

[ ] O versionamento do schema do banco de dados foi implementado.

[ ] Um rollback seguro de migração foi demonstrado e validado pela equipe.

[ ] Os repositórios transacionais foram implementados de acordo com a arquitetura do projeto.

[ ] Um serviço que consome os repositórios transacionais foi construído.

[ ] Testes transacionais iniciais foram realizados para garantir o funcionamento da persistência.

[ ] Os tempos de execução das consultas e transações foram coletados.

[ ] O repositório foi atualizado com o registro de todas as decisões técnicas tomadas durante a modelagem e testes.

[ ] A regra de não-antecipação foi respeitada, garantindo que recursos de aulas futuras não foram codificados nesta etapa.