1. Objetivo

Implementar a funcionalidade de assistente de documentação baseado em Retrieval-Augmented Generation (RAG). O sistema deve processar a documentação interna da aplicação (como README.md e especificações OpenAPI/Swagger), indexar os trechos (chunks) e suas representações em vetores (embeddings), e expor uma rota para responder a perguntas técnicas de forma precisa e contextualizada, fornecendo obrigatoriamente a citação exata das fontes.

2. Contexto

Seguindo a diretriz de desenvolvimento incremental (SpecDD) e o cronograma do MVP SynapseShop, a Aula 24 foca na camada de inteligência artificial aplicada ao suporte à documentação do projeto. Esta especificação define os requisitos para construção da ingestão de documentos, índice de busca por similaridade e integração com a LLM externa via API (provedores compatíveis com OpenAI / DeepSeek).

3. Arquitetura do Componente RAG

┌────────────────────────┐      ┌─────────────────────────┐
│     Documentos Base    │ ───► │ Pipeline de Ingestão    │
│ (README.md, openapi)   │      │ (Chunking + Embeddings) │
└────────────────────────┘      └────────────┬────────────┘
                                             │
                                             ▼
┌────────────────────────┐      ┌─────────────────────────┐
│  POST /api/v1/ask_docs │ ───► │  Índice de Conhecimento │
│  (Pergunta do Usuário) │      │   (SQLite / Dicionário) │
└───────────┬────────────┘      └────────────┬────────────┘
            │                                │
            ▼                                ▼
┌─────────────────────────────────────────────────────────┐
│  Recuperação de Contexto (Top-K por Cosseno / Threshold)│
└───────────────────────────┬─────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Chamada à LLM (Contexto + Pergunta) com Resposta + Citação│
└───────────────────────────┴─────────────────────────────┘


4. Requisitos Detalhados

4.1. Modelagem do Índice (Armazenamento Leve)

Implementar uma estrutura de persistência leve (usando SQLite ou dicionário em memória com arquivo de apoio):

Tabela/Estrutura documents:

doc_id (Identificador único)

path (Caminho relativo do arquivo, ex.: README.md, docs/openapi.yaml)

title (Título ou nome legível do documento)

hash (Hash do conteúdo para controle de atualizações/reindexação)

Tabela/Estrutura chunks:

chunk_id (Identificador único do bloco)

doc_id (Chave estrangeira vinculada a documents)

chunk_text (Conteúdo do bloco de texto)

start / end (Intervalo de caracteres ou posição no documento original)

embedding (Vetor de embedding serializado / BLOB)

4.2. Ingestão e Processamento de Documentos

Processar automaticamente o arquivo README.md e os ficheiros de documentação da API (ex.: openapi.json / openapi.yaml).

Estratégia de Chunking: Divisão de texto em blocos de aproximadamente ~400 tokens com overlap (sobreposição) de ~80 tokens.

Geração de Embeddings: Calcular os vetores de embedding para cada bloco e persistir o índice.

4.3. Algoritmo de Recuperação de Contexto (Retrieval)

Para cada pergunta recebida, gerar o respectivo vetor de embedding.

Calcular a similaridade por cosseno (cosine similarity) em relação aos chunks armazenados.

Filtrar os top_k blocos (padrão: 3 a 5) que atendam a um limiar mínimo de similaridade (min_score, ex.: 0.25).

Formatar o contexto recuperado com caminho, título e trecho para injeção no prompt da LLM.

4.4. Endpoint da API (POST /api/v1/ask_docs)

Expor a rota no serviço de IA da aplicação:

Payload de Entrada (Request JSON):

{
  "question": "Como rodar as migrações do banco de dados no projeto?",
  "top_k": 3,
  "min_score": 0.25
}


Payload de Saída (Response JSON):

{
  "answer": "Para executar as migrações do banco de dados, utilize o comando...",
  "sources": [
    {
      "path": "README.md",
      "title": "Documentação SynapseShop",
      "range": "1200-1450",
      "score": 0.87
    }
  ]
}

4.5. Limites e Respostas Guardrail

Caso a pontuação de similaridade de todos os blocos seja inferior a min_score, o assistente deve responder informando que a informação não foi encontrada na documentação do projeto, evitando alucinações sem fonte citada.

5. Requisitos de Entrega (Definition of Done)

[ ] A estrutura de armazenamento do índice RAG (documents e chunks) foi modelada e implementada.

[ ] O script/pipeline de ingestão processa o README.md e a documentação OpenAPI gerando os chunks e embeddings com a sobreposição adequada.

[ ] A busca vetorial por similaridade por cosseno está funcional com parâmetros de top_k e min_score.

[ ] A rota POST /api/v1/ask_docs foi exposta, validando entradas e retornando a resposta sintetizada acompanhada da lista de fontes (sources) com caminhos e pontuações.

[ ] Testes automatizados cobrem a funcionalidade da rota /ask_docs e o mecanismo de ordenação/filtro do índice.

[ ] O arquivo PROMPTS.md foi atualizado com as técnicas de engenharia de prompt utilizadas na elaboração e ajuste da recuperação contextual.

[ ] O README.md foi atualizado documentando a arquitetura do assistente RAG, parâmetros de indexação e instruções sobre como reindexar a documentação.

[ ] O escopo do projeto foi mantido estritamente isolado, respeitando as diretrizes de SpecDD e a restrição de escopo.