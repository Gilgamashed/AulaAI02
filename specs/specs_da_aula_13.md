Aqui está a especificação completa para a **Aula 13** do projeto **SynapseShop**, elaborada estritamente de acordo com a metodologia **SpecDD (Specification-Driven Development)** e com base nos requisitos pedagógicos do plano de curso.

---

# Spec: Documentação Completa da API com OpenAPI/Swagger e Postman/Insomnia (Aula 13)

## 1. Objetivo

Padronizar, enriquecer e publicar a documentação técnica da API do SynapseShop com a especificação OpenAPI/Swagger, assegurando convenções RESTful, esquemas de erro padronizados e a disponibilização de coleções para Postman/Insomnia com ambientes (*environments*) configurados.

## 2. Contexto

Na sequência do desenvolvimento de testes automatizados, a Aula 13 foca-se na documentação interativa e na padronização rigorosa dos contratos das interfaces da API. Respeitando a diretriz de desenvolvimento incremental (SpecDD), a equipa deve focar-se exclusivamente na documentação dos contratos de API existentes, sem antecipar implementações de inteligência artificial, mensageria avançada ou dashboards analíticos previstos para aulas posteriores.

## 3. Tarefas e Responsabilidades

* **Evolução do Ficheiro OpenAPI (`openapi.yaml` / `openapi.json`):**
* Atualizar o contrato OpenAPI com títulos, descrições detalhadas, tags, exemplos de pedido (*requestBody*) e resposta (*responses*).


* Definir o esquema padrão de erros (`ErrorSchema`) baseado em boas práticas ou na norma RFC 7807 (`problem+json`).




* **Padronização de Convenções e Cabeçalhos:**
* Estandardizar a nomenclatura de rotas, paginação (`page`, `limit`, `nextCursor`), filtros (`?status=`), ordenação (`sort=createdAt:desc`) e status codes (2xx, 4xx, 5xx).


* Mapear os cabeçalhos obrigatórios da aplicação (`Authorization`, `Idempotency-Key`, `X-Trace-Id`) nos componentes da especificação.




* **Validação Estática e Linter:**
* Executar a validação estática do ficheiro OpenAPI através de ferramentas de linting (como Spectral ou Redocly CLI) para corrigir eventuais avisos ou inconsistências.




* **Disponibilização de Documentação e Artefactos de Teste:**
* Configurar a disponibilização interativa da documentação da API (Swagger UI e ReDoc).


* Exportar as coleções atualizadas para o Postman ou Insomnia, incluindo *environments* com variáveis globais (`baseURL`, `token`, etc.) e exemplos operacionais.




* **Versionamento e Checklist do Integrador:**
* Criar a pasta `docs/` para guardar os ficheiros de documentação e registar o histórico de alterações no ficheiro `CHANGELOG.md`.


* Adicionar a Checklist do Integrador Externo no `README.md` ou na pasta `docs/`, contemplando URLs de ambiente, estratégias de autenticação, limites de utilização (*rate limits*) e política de alterações de versão.


* Atualizar o ficheiro `PROMPTS.md` com os prompts de IA utilizados no refinamento do contrato OpenAPI e na criação de exemplos.





## 4. Requisitos de Entrega (Definition of Done)

* [ ] O ficheiro de especificação OpenAPI (`openapi.yaml` ou `openapi.json`) foi atualizado e contempla esquemas completos de resposta e de erro padronizados (`ErrorSchema` / RFC 7807).


* [ ] Os endpoints da API estão estandardizados com suporte documentado para paginação, filtros, ordenação e cabeçalhos obrigatórios (`Authorization`, `Idempotency-Key`, `X-Trace-Id`).


* [ ] A validação estática (linting com Spectral ou Redocly CLI) foi executada e não apresenta erros no contrato OpenAPI.


* [ ] As interfaces interativas Swagger UI e ReDoc estão funcionais e acessíveis a partir da aplicação.


* [ ] A coleção do Postman ou Insomnia foi exportada e disponibilizada com *environments* e exemplos de requisição para cenários de sucesso e erro.


* [ ] A documentação do projeto foi versionada na pasta `docs/` e o histórico de alterações foi atualizado no ficheiro `CHANGELOG.md`.


* [ ] A Checklist do Integrador Externo foi incluída no `README.md` ou na pasta `docs/`, contendo as instruções necessárias para consumo da API por terceiros.


* [ ] O ficheiro `PROMPTS.md` foi atualizado com o histórico de interações com a IA generativa durante a elaboração do contrato OpenAPI e artefactos de documentação.


* [ ] O projeto continua a ser executado perfeitamente via `docker-compose up`, sem introduzir dependências ou código de etapas futuras fora do escopo da Aula 13.