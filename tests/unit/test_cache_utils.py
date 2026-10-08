"""Testes unitários dos utilitários de cache (Aula 12).

O `cache.py` concentra duas responsabilidades bem diferentes, e os testes
separam por elas:

**Montagem de chave** (`query_fingerprint`, `detail_key`, `details_key`,
`redis_url_publicavel`) — funções puras, onde um erro produz um bug
silencioso. A chave determinística errada faz duas requisições diferentes
compartilharem a mesma entrada de cache: o usuário vê o item de outro filtro.

**Comportamento** (`cache_aside`) — testado com cache em memória real, e
com exceção injetada para provar o fail-open.

O teste mais importante do arquivo é o de **redação da senha do Redis**: o
endpoint de métricas é administrativo, mas "administrativo" não significa
"público" no log. Se a credencial vazar para `GET /api/v1/cache/metrics/`, ela
vaza para o histórico de qualquer proxy que registrar a resposta.
"""

from decimal import Decimal

import pytest
from django.test import override_settings

from core import cache as cache_mod
from core.cache import (
    cache_aside,
    cache_habilitado,
    detail_key,
    details_key,
    query_fingerprint,
    redis_url_publicavel,
    to_json_safe,
)
from core.cache_metrics import cache_metrics

pytestmark = pytest.mark.unit


# =====================================================================
# Redação da credencial do Redis
# =====================================================================
@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        # Com senha: a parte antes de `@` é substituída, o host e a porta ficam.
        pytest.param(
            "redis://:senha-secreta@cache:6379/1",
            "redis://***@cache:6379/1",
            id="com_senha",
        ),
        # Sem senha: a forma pública permanece.
        pytest.param("redis://localhost:6379/1", "redis://***@localhost:6379/1", id="sem_senha"),
        pytest.param("redis://redis/1", "redis://***@redis/1", id="sem_porta"),
        # URL malformada/sem netloc: devolvida como veio, em vez de virar
        # "***@" e esconder o diagnóstico.
        pytest.param("", "", id="vazia"),
        pytest.param("redis-sentinel://", "redis-sentinel://", id="sem_netloc"),
    ],
)
def test_senha_do_redis_nunca_vaza(  # noqa: S105 — o teste nomeia o segredo de propósito
    url, esperado
):
    """A credencial do Redis não pode aparecer em resposta HTTP nem em log."""
    with override_settings(REDIS_URL=url):
        assert redis_url_publicavel() == esperado


def test_senha_nao_aparece_no_texto_publicado():
    """Redundante de propósito: falha se a URL vazar em qualquer forma.

    O `parametrize` acima fixa o formato exato da saída. Este fixa a
    propriedade de segurança, que vale mesmo que a implementação mude: a
    substring da senha não pode estar no resultado, venha de onde vier.
    """
    senha = "senha-que-nao-existe-em-lugar-nenhum"

    with override_settings(REDIS_URL=f"redis://:{senha}@cache:6379/1"):
        publicado = redis_url_publicavel()

    assert senha not in publicado


# =====================================================================
# Determinismo do fingerprint
# =====================================================================
def test_fingerprint_ignora_a_ordem_das_chaves():
    """Duas query strings com os mesmos filtros em ordens distintas
    precisam levar à mesma entrada de cache.

    Sem `sort_keys=True`, `?categoria=1&preco_min=10` e
    `?preco_min=10&categoria=1` seriam caches distintos para o mesmo
    resultado — o dobro de espaço e metade do acerto do cache.
    """
    a = query_fingerprint({"categoria": "1", "preco_min": "10"})
    b = query_fingerprint({"preco_min": "10", "categoria": "1"})

    assert a == b


def test_fingerprint_muda_quando_o_valor_muda():
    """Filtros diferentes precisam de chaves diferentes (o contrário seria
    servir o resultado de um filtro para outro)."""
    assert query_fingerprint({"preco_min": "10"}) != query_fingerprint({"preco_min": "20"})


def test_fingerprint_tem_12_caracteres():
    """O tamanho curto é deliberado.

    Limite de 250 caracteres por chave no Redis, e o hash não pode carregar o
    valor do filtro (a chave é visível em `redis-cli KEYS`).
    """
    assert len(query_fingerprint({"qualquer": "coisa"})) == 12


def test_fingerprint_aceita_valor_nao_serializavel():
    """`Decimal` e `date` aparecem em parâmetros de filtro.

    O `default=str` evita `TypeError` na hora de montar a chave — que
    quebraria a listagem inteira em vez de só perder o cache.
    """
    assert query_fingerprint({"data": Decimal("10.50"), "x": {1, 2}}) is not None


# =====================================================================
# Montagem de chaves
# =====================================================================
@pytest.mark.parametrize(
    ("prefixo", "id_", "esperado"),
    [
        pytest.param("item", 12, "item:12", id="inteiro"),
        pytest.param("categoria", 7, "categoria:7", id="outro_prefixo"),
        pytest.param("item", "abc", "item:abc", id="string"),
        pytest.param("item", None, "item:None", id="none"),
    ],
)
def test_detail_key(prefixo, id_, esperado):
    assert detail_key(prefixo, id_) == esperado


def test_details_key_extende_a_chave_de_detalhe():
    """A consulta pesada é uma chave separada da simples.

    Se fosse a mesma chave, o payload de `detalhes` (com agregações) seria
    servido para quem pediu só o detalhe.
    """
    assert details_key("item", 12) == detail_key("item", 12) + ":detalhes"
    assert details_key("item", 12) != detail_key("item", 12)


# =====================================================================
# Normalização do payload
# =====================================================================
def test_decimal_vira_string_como_no_json_do_drf():
    """O payload cacheado precisa ficar igual ao que o DRF devolveria.

    `Decimal` viraria float (perdendo precisão) se fosse serializado direto;
    o `DjangoJSONEncoder` mantém a string, que é o que o `JSONRenderer`
    entrega ao cliente.
    """
    assert to_json_safe({"total": Decimal("1999.90")}) == {"total": "1999.90"}


def test_lista_e_dict_sao_convertidos_para_tipo_nativo():
    """`ReturnList`/`ReturnDict` do DRF carregam referência ao Serializer.

    Picklear isso prenderia a entrada de cache à versão do DRF; a ida-e-volta
    por JSON quebra a referência. O `serializer=None` é o que o DRF usa
    quando o container não tem serializer associado (acontece em `.data`
    já materializado), e é suficiente para reproduzir a estrutura.
    """
    from rest_framework.utils.serializer_helpers import ReturnDict, ReturnList

    original = ReturnDict({"a": 1}, serializer=None)

    convertido = to_json_safe(original)

    assert type(convertido) is dict
    assert type(to_json_safe(ReturnList([1, 2], serializer=None))) is list


# =====================================================================
# Comportamento: cache-aside
# =====================================================================
def test_hit_nao_chama_o_producer():
    """No HIT o produtor (banco) não pode ser chamado — é o ponto do cache."""
    chamadas = []

    def producer():
        chamadas.append(1)
        return {"origem": "banco"}

    cache_aside("item:1", 60, "item", producer)  # popula
    resultado = cache_aside("item:1", 60, "item", producer)  # deve acertar

    assert resultado == {"origem": "banco"}
    assert len(chamadas) == 1, "o produtor rodou no HIT"


def test_miss_chama_o_producer_e_preenche():
    chamadas = []

    def producer():
        chamadas.append(1)
        return {"origem": "banco"}

    resultado = cache_aside("item:novo", 60, "item", producer)

    assert resultado == {"origem": "banco"}
    assert len(chamadas) == 1


def test_falha_do_producer_nao_cacheia_o_erro():
    """Exceção sobe e **nada** é cacheado.

    O caso perigoso seria o 404 virar "valor" no cache: o item criado em
    seguida não apareceria até o TTL expirar.
    """

    def producer():
        raise LookupError("não encontrado")

    with pytest.raises(LookupError):
        cache_aside("item:inexistente", 60, "item", producer)

    # Se o erro tivesse sido cacheado, esta chamada devolveria em vez de levantar.
    with pytest.raises(LookupError):
        cache_aside("item:inexistente", 60, "item", producer)


def test_chave_none_e_bypass_sem_lookup():
    """`chave=None` significa "sem cache possível" (Redis fora do ar).

    E o bypass **não** conta como lookup: o `record` retorna antes de
    incrementar o denominador, porque houve zero consulta ao cache. Contar
    como lookup faria a hit rate cair artificialmente numa indisponibilidade
    do Redis — que é justamente quando a métrica deixa de ser útil.
    """
    assert cache_aside(None, 60, "item", lambda: {"do_banco": True}) == {"do_banco": True}

    contadores = cache_metrics.snapshot()["item"]
    assert contadores.bypasses == 1
    assert contadores.lookups == 0


@override_settings(CACHE_ENABLED=False)
def test_cache_desabilitado_e_bypass():
    """`CACHE_ENABLED=False` é o switch do baseline de desempenho (Aula 8).

    Precisa ignorar o cache mesmo com chave válida — e o produtor tem de rodar,
    senão a comparação "antes/depois" da Aula 8 mediria uma API quebrada.
    """
    chamadas = []

    def producer():
        chamadas.append(1)
        return {"do_banco": True}

    cache_aside("item:1", 60, "item", producer)
    cache_aside("item:1", 60, "item", producer)

    assert len(chamadas) == 2, "com o cache desligado o produtor deve rodar sempre"


@override_settings(CACHE_ENABLED=True)
def test_cache_habilitado_reflete_o_setting():
    assert cache_habilitado() is True


@override_settings(CACHE_ENABLED=False)
def test_cache_habilitado_desligado():
    assert cache_habilitado() is False


def test_falha_de_leitura_do_cache_cai_para_o_banco(monkeypatch):
    """Fail-open: um Redis que responde erro não pode derrubar a leitura.

    Este é o teste que dá sentido ao try/except em volta de `cache.get`: sem
    ele, uma falha de rede no Redis viraria 500 na API inteira.
    """

    def leitura_quebrada(*args, **kwargs):
        raise cache_mod.RedisError("conexão recusada")

    monkeypatch.setattr(cache_mod.cache, "get", leitura_quebrada)

    assert cache_aside("item:1", 60, "item", lambda: {"do_banco": True}) == {
        "do_banco": True
    }