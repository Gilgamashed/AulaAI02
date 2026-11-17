# Gemini indisponível — quota diária esgotada (2026-11-16)

Tentativa de baseline Gemini da spec `01` registrada para não confundir
indisponibilidade do provedor com qualidade do pipeline.

## Configuração da tentativa

- **Provedor:** `LLM_PROVIDER=auto`
- **Modelo:** `gemini-3.5-flash`
- **Timeout por chamada:** 60 s
- **Tentativas por chamada:** 1
- **Limite do circuit breaker:** 50 falhas
- **Comando:** `python scripts/avaliar_ia.py --modo gemini --min-sucesso 0 --delay 0.5`

## Resultado

O provedor respondeu **HTTP 429 `RESOURCE_EXHAUSTED`**:

> Quota exceeded for metric: `generativelanguage.googleapis.com/generate_content_free_tier_requests`,
> limit: 20, model: `gemini-3.6-flash` — Generate content requests per day limit
> exceeded on Free Tier. Retry in ~9h.

**Referência do limite:** free tier com **20 requisições de `generateContent`
por dia**, por conta/projeto da chave. O valor pode mudar; consulte
[Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits). A
observação acima é de **2026-11-16**. O nome de modelo citado pelo provedor na
métrica (`gemini-3.6-flash`) pode variar em relação ao `LLM_MODEL` configurado.

O limite é da **free tier da chave usada** (20 requisições por dia), não do
código. As primeiras chamadas do run consumiram a cota restante e as demais
caíram para o mock pelo fallback de `auto` (53 de 58 chamadas com fallback). O
relatório desse run foi descartado: apresentar resultados de mock com rótulo
`gemini` seria enganoso.

## Conclusão

- O baseline válido desta rodada é o de **mock**, publicado em
  [`2026-11-16_2302_mock.md`](2026-11-16_2302_mock.md).
- O baseline Gemini fica **pendente** até a cota diária renovar (ou até haver
  uma chave com limite maior). A spec `01` aceita explicitamente o mock como
  mínimo quando o Gemini não está disponível.
- A spec `02` pode começar pelo mock; a comparação com Gemini deve ser
  refeita com a mesma configuração e o mesmo golden set.

## Como repetir

Depois do reset da cota:

```bash
LLM_PROVIDER=auto docker compose up -d --force-recreate api
python scripts/avaliar_ia.py --modo gemini --min-sucesso 0 --delay 1.0 --max-questions 20
```

O golden set completo tem 58 itens; com 20 requisições/dia, uma execução
completa exige mais de um dia. Cada run parcial é uma amostra e deve ser
comparado com amostras equivalentes. O baseline de mock continua sendo a
regressão diária e não consome cota.

Se o objetivo for medir o provedor sem fallback mascarar falhas, use
`LLM_PROVIDER=gemini` e registre `--modo gemini-estrito`.

## Segurança

Nenhuma chave, token ou credencial foi registrada neste documento. A mensagem
do provedor foi reproduzida apenas no trecho que descreve a cota.
