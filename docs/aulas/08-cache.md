# Cache-aside com Redis (Aula 8)

> Conteúdo extraído do README.md (registro da aula). O README mantém apenas o resumo e o link para aqui.

## Cache-aside com Redis (Aula 8)

### Redis na orquestração

O serviço `redis:7-alpine` entra no `docker-compose.yml` com `db 1` exclusivo
para o cache da API (o `db 0` fica livre para as aulas seguintes), sem
persistência (o cache é descartável por definição) e com `healthcheck`. A API
só sobe depois que o Redis responde a `PING`:

```yaml
redis:
  image: redis:7-alpine
  ports: ["6379:6379"]
  command: ["redis-server", "--save", "", "--appendonly", "no"]
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
```

O backend é o **nativo do Django** (`django.core.cache.backends.redis.RedisCache`,
disponível desde o Django 4.0) sobre o cliente `redis-py` — que já fala
`SETEX` (TTL) e `INCR` (o contador de geração da invalidação). Isso dispensa
uma dependência extra como o `django-redis`.

Chaves reais no Redis (prefixo `synapseshop` + db + nome do app):

```
synapseshop:1:item:list:g1:44136fa355b3     listagem, geração 1, filtro A
synapseshop:1:categoria:list:geracao        contador de geração
synapseshop:1:item:2                        detalhe simples
synapseshop:1:item:2:detalhes               consulta pesada
```

### O padrão cache-aside

`api/core/cache.py` centraliza o fluxo em um único ponto
(`consultar_com_cache`), usado pelas viewsets:

1. **MISS** — lê o Redis; sem valor, executa a consulta no PostgreSQL
   (serializer + renderer), grava o resultado com TTL e devolve;
2. **HIT** — devolve o payload guardado, sem tocar no banco;
3. **Falha no Redis** — loga `CacheDegradado` e devolve a resposta do banco
   (fail-open): o cache é otimização, não pode virar ponto único de falha.

Endpoints instrumentados: listagem de itens, detalhe simples de item, consulta
pesada `GET /api/v1/items/{id}/detalhes/` e listagem de categorias — os dois
primeiros tipos exigidos pela spec ("listagem" e "acesso a dados específicos").
A consulta pesada existe para dar sentido ao cache: ela cruza 4 `SELECT`s
(`COUNT`/`AVG`/`MIN`/`MAX` da categoria, até 3 itens mais caros e até 3 mais
recentes), custo que some no cache depois do primeiro acesso.

### Chaves e TTL

| Chave                       | Conteúdo                            | TTL  |
| --------------------------- | ----------------------------------- | ---- |
| `item:list:g{ger}:{hash}`   | página de listagem (JSON serializado) | 60 s |
| `categoria:list:g{ger}:{hash}` | página de listagem               | 60 s |
| `item:{id}`                 | detalhe simples                     | 300 s |
| `item:{id}:detalhes`        | consulta pesada                     | 300 s |

- As **listagens** levam um contador de geração (`item:list:geracao`) no nome da
  chave, e o `{hash}` é o *fingerprint* dos parâmetros que alteram o resultado
  (página, ordenação, busca, filtros). Duas listagens com filtros diferentes
  nunca colidem.
- Os **detalhes** não levam geração: a chave é derivada do `id` e a
  invalidação é por `delete`.
- TTLs são ajustáveis por `CACHE_TTL_LIST` / `CACHE_TTL_DETAIL`; são apenas uma
  rede de segurança, porque quem garante a correção dos dados é a invalidação
  por evento.
- `CACHE_ENABLED=false` desliga tudo (nenhuma leitura/escrita) — é o switch do
  baseline de desempenho.

### Invalidação por evento de domínio

A invalidação é feita por **sinais do Django** (`api/core/signals.py`), depois
do commit da transação (`transaction.on_commit`), para nunca invalidar algo que
ainda pode ser revertido por um `rollback`:

| Evento                        | Efeito                                                                                       |
| ----------------------------- | -------------------------------------------------------------------------------------------- |
| `ItemCriado` / `ItemAtualizado` / `ItemRemovido` | `delete` em `item:{id}` e `item:{id}:detalhes` + `INCR` em `item:list:geracao` |
| `CategoryCriada` / `CategoryAtualizada` / `CategoryRemovida` | `delete` em `categoria:{id}` + `INCR` em `categoria:list:geracao` **e** em `item:list:geracao` |
| `Item` com categoria alterada | idem `ItemAtualizado`                                                                        |

Dois detalhes que valem registro:

- **Listagens são invalidadas por geração, não por chave.** Sem isso, seria
  preciso varrer o Redis procurando `item:list:*` — o Django não oferece
  "delete por padrão de chave". Com o contador, um `INCR` invalida todas as
  listagens de uma vez e as chaves antigas expiram sozinhas (60 s).
- **Alterar a categoria invalida a listagem de itens**, não só a de categorias:
  a listagem de itens embute o nome da categoria, então o dado está
  desnormalizado em dois lugares e a invalidação precisa cobrir os dois.

### Métricas de eficácia (hit rate)

`GET /api/v1/cache/metrics/` (somente `admin`) expõe
`hits / (hits + misses)` por namespace e no total, além de `bypasses`,
`erros` e `invalidacoes`:

```json
{
  "cache_habilitado": true,
  "redis": {"url": "redis://***@redis:6379/1", "key_prefix": "synapseshop",
            "ttl_lista_s": 60, "ttl_detalhe_s": 300},
  "total": {"lookups": 417, "hits": 413, "misses": 4, "bypasses": 0,
            "erros": 0, "invalidacoes": 0, "hit_rate": 0.9904},
  "namespaces": {"item:list": {"lookups": 105, "hits": 104, "misses": 1,
                               "bypasses": 0, "erros": 0, "hit_rate": 0.9905}}
}
```

Os mesmos eventos saem em **log estruturado JSON** (logger `core.cache`), o que
permite ver o ciclo `miss → preenchimento → hit` ao vivo:

```powershell
docker compose logs -f api
```

```json
{"timestamp": "...", "level": "INFO", "logger": "core.cache", "evento": "CacheLookup",
 "namespace": "item:list", "chave": "item:list:g1:44136fa355b3", "resultado": "miss",
 "ttl_s": 60, "latencia_ms": 0.369, "preenchimento_ms": 33.822, "mensagem": "cache miss"}
{"timestamp": "...", "level": "INFO", "logger": "core.cache", "evento": "CacheLookup",
 "namespace": "item:list", "chave": "item:list:g1:44136fa355b3", "resultado": "hit",
 "latencia_ms": 0.519, "mensagem": "cache hit"}
{"timestamp": "...", "level": "INFO", "logger": "core.cache", "evento": "ItemAtualizado",
 "namespace": "item:detalhes", "chave": "item:2:detalhes", "resultado": "invalidacao",
 "motivo": "registro alterado: chave item:2:detalhes removida", "mensagem": "cache invalidacao"}
```

### Desempenho medido: antes x depois

Medido por `scripts/measure_cache.py` (HTTP de ponta a ponta, biblioteca
padrão), no mesmo ambiente dos dois lados: **501 itens e 4 categorias**
(26 páginas de 20), 100 requisições por endpoint, 3 de aquecimento, um cliente
sequencial. As taxas de throttling foram elevadas no entorno da medição para
que nenhum 429 contaminasse a amostra.

```powershell
# baseline (comportamento pré-Aula 8)
$env:CACHE_ENABLED = "false"; docker compose up -d api
.venv\Scripts\python.exe scripts\measure_cache.py --requests 100 --label "sem cache"

# com cache
$env:CACHE_ENABLED = "true"; docker compose up -d api
.venv\Scripts\python.exe scripts\measure_cache.py --requests 100 --label "com cache"
```

| Endpoint                   | Média sem cache | Média com cache | Δ média | p95 sem cache | p95 com cache | RPS sem cache | RPS com cache |
| -------------------------- | --------------- | --------------- | ------- | ------------- | ------------- | ------------- | ------------- |
| Listagem de itens          | 58,30 ms        | 33,50 ms        | −42,5 % | 87,79 ms      | 49,73 ms      | 17,1          | 29,7 (+73,7 %) |
| Detalhe de item            | 39,61 ms        | 31,63 ms        | −20,1 % | 61,14 ms      | 54,78 ms      | 25,2          | 31,5 (+25,0 %) |
| Detalhes (consulta pesada) | 53,01 ms        | 27,76 ms        | −47,6 % | 71,50 ms      | 39,58 ms      | 18,8          | 35,9 (+91,0 %) |
| Listagem de categorias     | 43,38 ms        | 29,90 ms        | −31,1 % | 68,83 ms      | 46,58 ms      | 23,0          | 33,3 (+44,8 %) |
| **Média dos 4 endpoints**   | **48,58 ms**    | **30,70 ms**    | **−36,8 %** | —         | —             | **21,0**      | **32,6 (+55,1 %)** |

Hit rate da rodada com cache: **99,0 %** (413 hits / 417 lookups; os 4 misses
são exatamente a primeira requisição de cada namespace). As colunas `1ª fria`
(primeira requisição, ainda sem chave) e `média ss` (regime permanente) ficam
no relatório do script.

Como ler estes números com honestidade:

- o ganho é de **regime permanente**; a primeira requisição de cada chave paga
  o MISS (banco + escrita no Redis) e é, em geral, mais cara que sem cache —
  é o preço de entrada do cache;
- o RPS é de **um cliente sequencial**: serve para comparar os dois cenários
  nas mesmas condições, não como limite de capacidade;
- o ganho é menor no detalhe simples (39,6 → 31,6 ms) porque ele já é um único
  `SELECT` por `pk`; o cache economiza o little round-trip ao banco, mas não
  há agregação cara para evitar.

### Modo degradado: Redis fora do ar

Com o Redis parado, a API **continua respondendo 200** — todas as requisições
caem no banco e cada falha é registrada (`CacheDegradado` / `erro` nas
métricas). O custo é a latência: como o time-out de socket é de 1 s, cada
requisição leva cerca de 3,4 s até o banco responder. A leitura é
intencionalmente rápida e barulhenta em vez de silenciosa, para que a queda do
cache apareça no log e no dashboard.


