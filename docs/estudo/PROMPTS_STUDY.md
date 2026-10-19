# 1. Impacto dos parâmetros globais da LLM

## Temperatura

A temperatura influencia em *como* um modelo LLM escolhe a próxima palavra em uma sequência, introduzindo um pouco de aleatoriedade e criatividade no texto gerado.

- **Temperatura baixa (0.3 ou menos):** faz com que o modelo quase sempre prefira a opção de maior chance em uma cadeia de texto, diminuindo a criatividade e flexibilidade, mas providenciando respostas mais factuais e determinísticas.
- **Temperatura alta (0.7 pra cima):** faz com que palavras menos comuns ou mais surpreendentes tenham chances melhores de serem selecionadas, dando mais variedade e criatividade às respostas, porém também aumenta a chance de incoerências, alucinações e respostas estranhas.

## Limite de tokens

É o quão longa a resposta de uma LLM deve ser. A janela de contexto é o quanto uma LLM é capaz de processar. Uma janela de `max_tokens` maior vai providenciar respostas mais prolixas, mas vai também consumir mais espaço na janela de contexto total. Caso a janela de contexto fique apertada, a LLM pode truncar a resposta, parando de responder abruptamente, muitas vezes no meio da frase, ou atingindo o teto da janela de contexto em caso de conversas longas, interrompendo a geração mesmo se o `max_tokens` não tiver sido atingido.

Provedores de API cobram por volume de tokens, e output tokens são significativamente mais caros. Um `max_tokens` alto pode levar o modelo a se tornar prolixo demais, o que pode levar a custos elevados se o comportamento não for controlado por system prompts ou temperaturas baixas.

# 2. Técnicas de prompting

## Zero-shot

É uma técnica em que pedimos à LLM realizar uma tarefa sem oferecer nenhum exemplo. Simplesmente damos uma instrução e esperamos uma resposta baseada em dados de treinamento pré-existentes.

Ex.:

```text
Você é um assistente DevOps de backend. Categorize os erros no log da aplicação em uma dessas categorias: DATABASE, AUTHENTICATION, NETWORK, UNKNOWN.
Responda APENAS com um objeto JSON válido contendo as chaves "category" e "severity_score" (uma escala de 1-10 baseada no impacto do erro). Não inclua nenhum texto conversacional ou formatação markdown que não seja JSON.
Log: [log incluído aqui]
```

## Few-shot

Nessa técnica, estabelecemos alguns exemplos providenciando o input e output desejado para a LLM se basear para realizar sua tarefa final.

Ex.:

```text
Você é um serviço backend de ingestão de dados. Seu trabalho é extrair dados estruturados e ordenados de mensagens escritas em estilo livre por clientes para um formato JSON. 
### EXEMPLOS ###
Input: "Oi, me vê duas pizzas de pepperoni e uma coca-cola zero por favor. Endereço é Rua Larga, 123."
Output:
[
    {"item": "pizza de pepperoni", "quantidade": 2, "especificacoes": null},
    {"item": "coca-cola", "quantidade": 1, "especificacoes": "zero"}
]
Input: "Boa noite, quero um hambúrguer duplo sem cebola e duas águas com gás."
Output:
[
    {"item": "hambúrguer duplo", "quantidade": 1, "especificacoes": "sem cebola"},
    {"item": "água", "quantidade": 2, "especificacoes": "com gás"}
]
Input: "Duas porções de batata frita e um milkshake de chocolate, por gentileza."
Output:
[
    {"item": "batata frita", "quantidade": 2, "especificacoes": null},
    {"item": "milkshake de chocolate", "quantidade": 1, "especificacoes": null}
]
```

## Chain of thought

Uma técnica onde, ao invés de pular direto na pergunta, oferecemos uma linha de raciocínio ao modelo LLM. Isso ajuda o modelo a entender a lógica e melhora a precisão do modelo ao abordar problemas complexos com várias camadas.

Ex.:

```text
Você é um consultor de operações sênior. Precisamos criar regras de negócio automatizadas no backend para o processamento de solicitações de reembolso de clientes.
Antes de me fornecer a lista final de regras, pense no processo passo a passo. Descreva seu raciocínio em cada fase:
1. Identifique os riscos potenciais de fraude.
2. Considere os custos operacionais do frete de devolução.
3. Formule as condições lógicas (Se/Então) que o sistema deve seguir.
```

# 3. Análise de falhas e mitigação

## Alucinação

Modelos LLM não sabem necessariamente o que é "verdade", eles sabem apenas o que é estatisticamente mais provável. Quando um modelo gera um texto que é factualmente incorreto, sem sentido ou destacado da realidade,  enquanto soa completamente confiante, fluente e persuasivo, dizemos que o modelo alucinou.

## Como evitar ou minimizar

- **Reduzir a temperatura:** para respostas mais técnicas e focadas.
- **Usar chain-of-thought:** força a LLM a verificar se sua própria lógica faz sentido antes de concluir.
- **Usar documentação relevante para limitar o contexto:** auxiliamos assim o modelo a gerar uma resposta baseada no que foi providenciado.
- **Agentes críticos:** técnica em que duas LLMs operam como gerador/crítico, onde o crítico opera especificamente procurando por inconsistências nas respostas e oferece feedback ao gerador.
