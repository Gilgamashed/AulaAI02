# Spec: CRUD da API Principal com Django REST Framework (Aula 4)

## 1. Objetivo
Implementar a estrutura inicial da API principal utilizando Django REST Framework (DRF). O objetivo é expor os primeiros recursos transacionais com operações CRUD completas sob rotas versionadas (`/api/v1/`), utilizando modelos, serializadores, viewsets e roteadores padronizados.

## 2. Contexto
Após estruturar o ambiente de contêineres na Aula 3, a equipe inicia o desenvolvimento do gateway/core do backend. Seguindo rigorosamente a diretriz incremental SpecDD, não devem ser implementados neste momento: autenticação JWT (Aula 7), microsserviços em FastAPI (Aula 5), cache com Redis (Aula 8) ou mensageria (Aulas 9–11). O foco exclusivo é a construção e validação da camada de API do DRF.

## 3. Tarefas e Responsabilidades
* **Modelagem e Serialização:** Modelar as entidades base da aplicação (como `Item`/`Produto` e `Category`) utilizando os recursos do ORM do Django e criar seus respectivos `ModelSerializers` com validações de payload e tipagem de campos.
* **ViewSets e Roteamento:** Construir `ModelViewSets` para centralizar a lógica das operações CRUD (*List*, *Retrieve*, *Create*, *Update*, *Delete*) e registrar as rotas no `DefaultRouter` sob o prefixo de versão `/api/v1/`.
* **Construção do Checklist "IA-Safe":** Elaborar e adotar um guia de checagem para códigos gerados por IA generativa (revisão de imports, tipos de dados, validações customizadas e retornos de status HTTP adequados).
* **Documentação das Rotas & PROMPTS.md:** Testar as requisições via Postman/Insomnia e atualizar a documentação no repositório, além de registrar os prompts e ajustes manuais no arquivo `PROMPTS.md`.

## 4. Requisitos de Entrega (Definition of Done)
- [ ] O framework Django REST Framework (DRF) está configurado e integrado ao ambiente conteinerizado.
- [ ] As entidades principais (ex.: `Category` e `Item`) estão modeladas com seus respectivos Models, Serializers e ViewSets.
- [ ] Endpoints RESTful funcionais expostos sob o prefixo `/api/v1/items/` e `/api/v1/categories/`.
- [ ] Respostas da API alinhadas aos verbos e status codes padrão HTTP (200 OK, 201 Created, 204 No Content, 400 Bad Request, 404 Not Found).
- [ ] O checklist "IA-safe" foi criado no repositório e aplicado ao revisar o código sugerido por assistentes virtuais.
- [ ] As rotas criadas foram salvas e exportadas em uma coleção do Postman ou Insomnia no diretório do projeto.
- [ ] O arquivo `PROMPTS.md` foi atualizado com o histórico de prompts utilizados para a criação dos componentes da API e com o registro das intervenções manuais.
- [ ] O escopo manteve-se restrito à Aula 4, garantindo a ausência de bibliotecas de autenticação JWT, Redis, FastAPI ou filas de mensageria.