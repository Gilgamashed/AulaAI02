# Spec: Testes Automatizados e Cobertura (Aula 12)

## 1. Objetivo

Configurar e executar testes unitários e de integração utilizando a ferramenta `pytest` no ambiente conteinerizado, garantindo a estabilidade e a qualidade da aplicação através da medição de cobertura de código e da correta aplicação de *mocks* e *fixtures*.

## 2. Contexto

Seguindo estritamente a diretriz de desenvolvimento incremental (SpecDD) da SynapseTech, esta etapa foca-se exclusivamente na implementação da infraestrutura e dos casos de teste. Embora o bloco das aulas 12 e 13 abranja testes e documentação de API, a Aula 12 restringe-se à criação da suíte de testes. É expressamente proibida a antecipação de tarefas relacionadas com o OpenAPI, Swagger, Postman ou Insomnia, as quais pertencem ao escopo da Aula 13.

## 3. Tarefas e Responsabilidades

* **Estruturação da Suíte:** Organizar as pastas do projeto para os testes (`tests/unit` e `tests/integration`), bem como configurar o ficheiro central `conftest.py`.


* **Fixtures e Mocks:** Criar *fixtures* base que incluam a aplicação de teste, um cliente HTTP, uma base de dados efémera e um relógio fixo. Adicionalmente, devem ser implementados *mocks* e *fakes* para isolar o sistema de dependências externas.


* **Testes Unitários:** Desenvolver testes parametrizados para os utilitários (*utils*) e serviços da aplicação, contemplando obrigatoriamente os caminhos felizes e os cenários de erro.


* **Testes de Integração:** Criar testes que validem o ciclo de vida completo de um recurso na API (por exemplo, executar um `POST /recurso` e, de seguida, um `GET /recurso/{id}`), assegurando a devolução dos *status codes* corretos e os respetivos efeitos na base de dados.


* **Execução e Estabilização:** Executar os testes dentro do contêiner utilizando o comando para recolha de cobertura (`pytest --cov`) e aplicar técnicas para estabilizar eventuais testes intermitentes (como isolar processos de I/O, congelar o tempo ou fixar uma semente).



## 4. Requisitos de Entrega (Definition of Done)

* [ ] A estrutura da suíte de testes encontra-se perfeitamente organizada, contendo os diretórios `tests/unit`, `tests/integration` e o ficheiro `conftest.py`.


* [ ] As *fixtures* globais (escopos apropriados) e os *mocks* para serviços externos foram configurados com sucesso.


* [ ] Foram desenvolvidos testes unitários parametrizados que cobrem satisfatoriamente os *utils* críticos e as lógicas de serviço.


* [ ] Existe, pelo menos, um teste de integração funcional a validar endpoints da API e os reflexos na base de dados.


* [ ] A meta mínima de cobertura estipulada pela equipa (por exemplo, 85% global e 100% nos utilitários críticos) foi atingida localmente.


* [ ] O ficheiro `README.md` foi atualizado para incluir os comandos necessários à execução dos testes, as convenções adotadas pela equipa e as metas de cobertura.


* [ ] Todas as pendências técnicas ou melhorias identificadas foram registadas como *issues* no repositório do GitHub.