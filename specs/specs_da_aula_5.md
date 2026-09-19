# Spec: Microsserviço Complementar com FastAPI (Aula 5)

## 1. Objetivo
O objetivo desta especificação é orientar o desenvolvimento do microsserviço complementar de estoque (inventory) utilizando o framework FastAPI. A implementação deve focar na criação de endpoints estruturados, utilizando tipagem estática e validando a documentação automática das rotas gerada pelo framework.

## 2. Contexto
Seguindo a diretriz rigorosa de desenvolvimento incremental (SpecDD), esta etapa é dedicada exclusivamente à criação e integração do microsserviço em FastAPI. A equipe deve aproveitar as vantagens do framework para microsserviços e integrá-lo ao ecossistema conteinerizado do MVP SynapseShop. É terminantemente proibido antecipar a modelagem relacional de banco de dados (que ocorrerá na Aula 6) ou configurar sistemas de autenticação (Aula 7) neste momento.

## 3. Tarefas e Responsabilidades
- Utilizar inteligência artificial generativa para criar o esqueleto (scaffold) do microsserviço FastAPI.
- Elaborar prompts de IA que descrevam explicitamente os modelos Pydantic, dependências e respostas padrão desejadas.
- Aplicar boas práticas para a validação das respostas sugeridas e da tipagem estática nos endpoints.
- Definir e alinhar quais serão as rotas mínimas obrigatórias a serem mantidas no microsserviço de inventário.
- Integrar o novo serviço de API ao orquestrador `docker-compose.yml`.
- Criar e versionar um arquivo nomeado `PROMPTS-TEMPLATE.md` para padronizar entre os times como descrever requisitos, restrições e formatos de saída esperados ao acionar ferramentas de IA.

## 4. Requisitos de Entrega (Definition of Done)
- [x] O scaffold do microsserviço inventory em FastAPI foi gerado contendo modelos Pydantic e respostas padrão.
- [x] A tipagem estática e as validações de respostas da API foram devidamente implementadas e verificadas.
- [x] As rotas mínimas exigidas para o microsserviço foram alinhadas e construídas pela equipe.
- [x] O serviço FastAPI foi perfeitamente integrado ao ambiente orquestrado via `docker-compose.yml`.
- [x] A documentação interativa e automática do FastAPI foi validada e está acessível com sucesso através do endpoint `/docs`.
- [x] O arquivo `PROMPTS-TEMPLATE.md` foi adicionado ao repositório para orientar e padronizar os templates de prompts da equipe.
- [x] O escopo do projeto foi mantido completamente isolado, não contendo implementações antecipadas de banco de dados ou autenticação.