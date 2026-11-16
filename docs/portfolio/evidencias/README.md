# Evidências do Portfólio

Artefatos que provam, fora de uma apresentação ao vivo, que um incremento da
fase 2 funciona. A meta-spec
[`specs02/00_diretriz_incremental_specdd_fase2.md`](../../../specs02/00_diretriz_incremental_specdd_fase2.md)
exige que todo incremento concluído deixe pelo menos um item aqui.

## Estrutura

```
docs/portfolio/evidencias/
├── ia/            # relatórios do golden set, taxas, latência, custo
├── deploy/        # URL pública, health checks, capturas da demo
├── performance/   # resultados de carga e comparações
├── seguranca/     # auditorias, scans, decisões e limites aceitos
└── capturas/      # PNG/GIF de telas e fluxos
```

## Convenção de nomes

`AAAA-MM-DD_slug.ext` — data da execução, não do commit. Exemplos:

- `2026-11-20_baseline-ia-mock.json`
- `2026-11-20_baseline-ia-gemini.md`
- `2026-11-25_demo-publica.png`
- `2026-12-01_carga-k6.md`

Quando houver mais de uma execução no mesmo dia, acrescente `_HHMM`:
`2026-11-20_1430_pos-sql-v2_gemini.json`.

## Regras

- **Sem segredos.** Nunca incluir `.env`, chave de API, token JWT, senha demo
  em texto além da documentada no README, cookie ou header `Authorization`.
- **Sem PII real.** Dados de demonstração são fictícios e gerados por
  `seed_auth`/`seed_demo`.
- **Tamanho:** cada arquivo até **5 MB**. Screenshots em PNG; fluxos longos em
  GIF de até 5 MB ou link externo (YouTube/Drive) documentado no `.md`.
- **Relatórios brutos são JSON + resumo Markdown.** O `.md` precisa declarar:
  commit, data, ambiente, provedor/modelo, comando executado e limitações.
- **Números, não adjetivos.** Toda afirmação de melhoria referencia dois
  arquivos: antes e depois.
- **Evidência não substitui teste.** Um gráfico não cobre o que um teste
  automatizado cobre; os dois convivem.
- **Limpeza:** relatórios de execuções exploratórias descartadas ficam fora do
  repositório; só entra o que sustenta uma decisão.

## Como referenciar

- Na spec do incremento: link direto para o arquivo em
  `## 5. Métricas de sucesso e evidências`.
- No [`specs02/README.md`](../../../specs02/README.md): coluna ou nota do
  incremento concluído.
- No README de portfólio (incremento futuro): apenas os artefatos que contam a
  história principal, sem virar galeria.
