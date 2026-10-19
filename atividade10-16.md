Crie um dicionario documentando cada pasta e arquivo do projeto, 
explicando de forma simples sua função e importância. 
O objetivo é conhecer melhor a estrutura do projeto e desenvolver uma visão geral 
de suas funcionalidade s e rtecnologias, para conseguir explicar suas competencias 
e decisoes tecnicas  aso seja questionado por um entrevistador ou profissional de TI


## .github
    Pasta padrão para interação com a plataforma GitHub. Serve para guardar arquivos de configuração do github, workflows automatizadas, e templates de gerenciamento de comunidades no github

## .mypy_cache
    Gerada automaticamente pelo Mypy, o verificador de tipagem padrão do Python. Guarda o cache de testes de tipagem para acelerar verificações subsequentes.

## .opencode
    Guarda configurações, comandos customizados, plugins de um agente IA especifico do projeto.

## .pytest_cache
    Armazena dados temporarios das execuções de testes do framework 'pytest' pra otimizar e acelerar as próximas rodadas de testes.

## .ruff_cache
    Armazena dados temporarios para acelerar a execução do Ruff, um linter e formatador de código extremamente rápido.

## .spectral-tools
    ??? gerados pelo script 'lint-openapi.ps1' na pasta scripts.

## .venv
    Diretorio de ambiente virtual do projeto, permite isolar as dependências e o interpretador Python de um projeto específico. Facilita que o projeto funcione do mesmo jeito em diferentes máquinas.

## api
    Pasta que centraliza e organiza os arquivos que definem, configuram ou implementam os endpoints do projeto. No caso deste projeto, esta pasta está contendo os arquivos do framework Django.
        - /config
            Pasta de configurações do DRF
        - /core
            Pasta onde os principais códigos do projeto estão presentes. Inclui serviços de LLM, menssageria, migrations da database, models, views, 

            - /messaging
                comandos dos workers kafka e rabbitmq
                
        - /workers
            ??? Aparentemente não tem nada.


## collections
    Pasta onde as collections do Postman estão guardadas. Agrupa arquivos JSON que contêm conjuntos de requisições HTTP prontas (GET,POST,etc). Permique que desenvolvedores e testadores executem testes automatizados organizados por módulos da API (ex: auth.json, users.json).

## docs
    Armazena toda documentação oficial, técnica e de suporte do sistema. Contem o contrato openapi.yaml, changelog.md e contratos de eventos publicados no broker (pagamento registrado e pedido criado).

## htmlcov
    Contém o relatório visual de cobertura de código gerado em formato HTML. Criado automaticamente por ferramentas de análise de testes.

## repositories
    ??? está vazio

## scripts
    Serve para armazenar arquivos executáveis, automações e tarefas utilitárias que auxiliam no desenvolvimento, implantação ou manutenção do sistema. No nosso caso, temos um 'measure_cache.py' (script para comparar tempo de load com e sem cache) e um 'measure_messaging.py' (script para medir latencia ponta a ponta do pedido e efeito de indempodencia.)

## services
    Armazena microserviços do API, no nosso caso é onde o FastAPI controla o serviço de inventório do projeto

## specs
    Pasta que guarda todas as Specs para guiar o desenvolvimento orientado a IA (Spec-Driven Development). Nessa abordagem, as especificações escritas em formato legígel por humanos e máquinas se tornam a verdade absoluta e o código gerado é um reflexo gerável e validável a partir dessas especificações.

## tests
    Diretório que contem todos os testes do projeto. No caso desse projeto tem uma pasta para testes unitários e uma para teste de integração.

## (raiz do projeto)
    Não sei exatamente o que deveria estar aqui, mas hoje temos o README.md, .env, .gitignore, os arquivos do docker, documentação da IA no PROMPTS.md
