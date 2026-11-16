"""Testes do harness de avaliação de IA (fase 2, spec 01).

O script é exercitado com clientes HTTP falsos: nenhum teste abre socket,
chama o Gemini ou depende da stack no ar. O golden set real é validado, mas
as chamadas são sempre simuladas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import avaliar_ia

pytestmark = pytest.mark.unit

RAIZ = Path(__file__).resolve().parents[2]
GOLDEN = RAIZ / "scripts" / "avaliacao_ia" / "golden_set.json"


def _resposta(
    status: int, dados=None, texto: str = ""
) -> avaliar_ia.Resposta:
    if not texto:
        texto = json.dumps(dados) if dados is not None else ""
    return avaliar_ia.Resposta(status=status, dados=dados, texto=texto)


class ClienteFalso:
    """Responde por caminho; levanta o valor quando ele for uma exceção."""

    def __init__(self, respostas: dict[str, object]) -> None:
        self.respostas = respostas
        self.chamadas: list[tuple[str, str]] = []

    def requisitar(self, metodo, caminho, *, corpo=None, headers=None):
        self.chamadas.append((metodo, caminho))
        valor = self.respostas.get(caminho)
        if valor is None:
            raise AssertionError(f"chamada inesperada: {metodo} {caminho}")
        if isinstance(valor, Exception):
            raise valor
        return valor


def _item(
    *,
    tipo: str = "consulta",
    categoria: str = "contagem",
    endpoint: str = "/api/v1/ask_sql/",
    esperado: dict | None = None,
) -> dict:
    return {
        "id": f"teste-{tipo}",
        "categoria": categoria,
        "endpoint": endpoint,
        "pergunta": "Quantos pedidos existem?",
        "tipo_resultado": tipo,
        "esperado": esperado or {"status": 200, "colunas_min": ["total_pedidos"]},
        "tags": ["ci_mock"],
    }


def _resultado(
    identificador: str,
    *,
    categoria: str,
    tipo: str,
    sucesso: bool,
    falha: str | None = None,
) -> avaliar_ia.ResultadoItem:
    return avaliar_ia.ResultadoItem(
        id=identificador,
        categoria=categoria,
        endpoint="/api/v1/ask_sql/",
        tipo_resultado=tipo,
        pergunta="pergunta",
        status_http=200 if sucesso else 422,
        sucesso=sucesso,
        falha=falha,
        detalhe="",
        latencia_ms=10.0,
        colunas=[],
        linhas=0,
        fontes=0,
        tokens_prompt=1,
        tokens_output=1,
    )


# =====================================================================
# Golden set
# =====================================================================
def test_golden_set_real_atende_ao_contrato():
    dados = avaliar_ia.carregar_golden_set(GOLDEN)

    assert dados["versao"] == 1
    assert len(dados["itens"]) >= 46
    categorias = {item["categoria"] for item in dados["itens"]}
    assert set(avaliar_ia.CATEGORIAS_MINIMOS) <= categorias
    assert sum(1 for item in dados["itens"] if "ci_mock" in item["tags"]) >= 20


def test_dry_run_sai_0_e_resume_o_golden_set(capsys):
    assert avaliar_ia.main(["--dry-run", "--golden-set", str(GOLDEN)]) == 0

    saida = capsys.readouterr().out
    assert "Golden set válido" in saida
    assert "58 itens" in saida


def test_dry_run_com_json_invalido_sai_2(tmp_path, capsys):
    caminho = tmp_path / "golden.json"
    caminho.write_text("{}", encoding="utf-8")

    assert avaliar_ia.main(["--dry-run", "--golden-set", str(caminho)]) == 2
    assert "Configuração inválida" in capsys.readouterr().err


def test_validacao_rejeita_id_duplicado():
    dados = json.loads(GOLDEN.read_text(encoding="utf-8"))
    dados["itens"].append(dict(dados["itens"][0]))

    with pytest.raises(avaliar_ia.GoldenSetInvalido, match="duplicado"):
        avaliar_ia.validar_golden_set(dados)


def test_validacao_rejeita_categoria_desconhecida():
    dados = json.loads(GOLDEN.read_text(encoding="utf-8"))
    dados["itens"][0]["categoria"] = "inexistente"

    with pytest.raises(avaliar_ia.GoldenSetInvalido, match="categoria desconhecida"):
        avaliar_ia.validar_golden_set(dados)


def test_validacao_rejeita_minimo_por_categoria():
    dados = json.loads(GOLDEN.read_text(encoding="utf-8"))
    dados["itens"] = [
        item
        for item in dados["itens"]
        if item["categoria"] != "contagem" or item["id"] == "sql-contagem-01"
    ]

    with pytest.raises(avaliar_ia.GoldenSetInvalido, match="contagem"):
        avaliar_ia.validar_golden_set(dados)


def test_validacao_rejeita_ci_mock_insuficiente():
    dados = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for item in dados["itens"]:
        item["tags"] = [tag for tag in item["tags"] if tag != "ci_mock"]

    with pytest.raises(avaliar_ia.GoldenSetInvalido, match="ci_mock"):
        avaliar_ia.validar_golden_set(dados)


def test_validacao_exige_consulta_fora_do_mock():
    dados = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for item in dados["itens"]:
        if item["tipo_resultado"] == "consulta" and "ci_mock" not in item["tags"]:
            item["tags"].append("ci_mock")

    with pytest.raises(avaliar_ia.GoldenSetInvalido, match="fora do mock"):
        avaliar_ia.validar_golden_set(dados)


def test_validacao_rejeita_endpoint_incoerente():
    dados = json.loads(GOLDEN.read_text(encoding="utf-8"))
    dados["itens"][0]["endpoint"] = "/api/v1/ask_docs/"

    with pytest.raises(avaliar_ia.GoldenSetInvalido, match="exige endpoint"):
        avaliar_ia.validar_golden_set(dados)


# =====================================================================
# Classificação
# =====================================================================
def test_consulta_sucesso_com_colunas_e_linhas():
    classificacao = avaliar_ia._classificar(
        _item(),
        200,
        {
            "columns": ["total_pedidos"],
            "row_count": 1,
            "meta": {"tokens_prompt": 10, "tokens_output": 5},
        },
        "",
    )

    assert classificacao.sucesso is True
    assert classificacao.falha is None
    assert classificacao.tokens_prompt == 10
    assert classificacao.tokens_output == 5


def test_consulta_sem_coluna_esperada_falha():
    classificacao = avaliar_ia._classificar(
        _item(), 200, {"columns": ["outra"], "row_count": 1}, ""
    )

    assert classificacao.sucesso is False
    assert classificacao.falha == "resposta_inesperada"
    assert "total_pedidos" in classificacao.detalhe


def test_consulta_abaixo_do_minimo_de_linhas_falha():
    item = _item(esperado={"status": 200, "colunas_min": [], "linhas_min": 1})

    classificacao = avaliar_ia._classificar(
        item, 200, {"columns": [], "row_count": 0}, ""
    )

    assert classificacao.sucesso is False
    assert "abaixo do mínimo" in classificacao.detalhe


def test_recusa_esperada_aceita_422_e_rejeita_200():
    item = _item(tipo="recusa_esperada", esperado={"status": 422})

    aceita = avaliar_ia._classificar(
        item, 422, {"detail": "a pergunta não pode ser respondida"}, ""
    )
    rejeita = avaliar_ia._classificar(
        item, 200, {"columns": ["id"], "row_count": 1}, ""
    )

    assert aceita.sucesso is True
    assert rejeita.sucesso is False
    assert rejeita.falha == "resposta_inesperada"


def test_guardrail_esperado_exige_sem_fonte_e_frase_padrao():
    item = _item(
        tipo="guardrail_esperado",
        categoria="rag_fora_corpus",
        endpoint="/api/v1/ask_docs/",
        esperado={"status": 200, "fontes_min": 0},
    )

    ok = avaliar_ia._classificar(
        item,
        200,
        {
            "answer": "Não encontrei essa informação na documentação do projeto.",
            "sources": [],
        },
        "",
    )
    com_fonte = avaliar_ia._classificar(
        item, 200, {"answer": "resposta", "sources": [{"path": "README.md"}]}, ""
    )

    assert ok.sucesso is True
    assert com_fonte.sucesso is False


def test_rag_tecnico_exige_fonte_e_citacao():
    item = _item(
        tipo="rag_tecnico",
        categoria="rag_tecnico",
        endpoint="/api/v1/ask_docs/",
        esperado={"status": 200, "fontes_min": 1, "citacao": True},
    )

    ok = avaliar_ia._classificar(
        item, 200, {"answer": "Resposta [1]", "sources": [{"path": "README.md"}]}, ""
    )
    sem_fonte = avaliar_ia._classificar(item, 200, {"answer": "Resposta", "sources": []}, "")
    sem_citacao = avaliar_ia._classificar(
        item, 200, {"answer": "Resposta", "sources": [{"path": "README.md"}]}, ""
    )

    assert ok.sucesso is True
    assert sem_fonte.falha == "sem_fonte"
    assert sem_citacao.falha == "sem_citacao"


def test_assist_exige_answer():
    item = _item(
        tipo="assist",
        categoria="assist",
        endpoint="/api/v1/assist/",
        esperado={"status": 200, "modo": "summarize", "resposta_min": 1},
    )

    ok = avaliar_ia._classificar(
        item, 200, {"answer": "Resumo", "meta": {"tokens_prompt": 2, "tokens_output": 3}}, ""
    )
    vazio = avaliar_ia._classificar(item, 200, {"answer": ""}, "")

    assert ok.sucesso is True
    assert ok.tokens_prompt == 2
    assert vazio.falha == "resposta_vazia"


def test_avaliar_item_com_falha_de_rede_classifica_timeout():
    cliente = ClienteFalso(
        {"/api/v1/ask_sql/": avaliar_ia.FalhaRede("timed out")}
    )

    resultado = avaliar_ia.avaliar_item(cliente, "token", _item())

    assert resultado.status_http is None
    assert resultado.sucesso is False
    assert resultado.falha == "timeout"


@pytest.mark.parametrize(
    ("status", "detalhe", "esperado"),
    [
        (401, {"detail": "sem token"}, "auth"),
        (403, {"detail": "restrito"}, "auth"),
        (429, {"detail": "limite"}, "http_4xx_inesperado"),
        (500, {"detail": "falhou"}, "http_5xx"),
        (
            503,
            {"detail": "O índice de documentação ainda não foi construído."},
            "indice_ausente",
        ),
        (
            422,
            {"detail": "a pergunta não pode ser respondida com o schema disponível"},
            "nao_suportado",
        ),
        (422, {"detail": "tabela fora da allow-list: foo"}, "sql_proibido"),
        (422, {"detail": "SELECT * não é permitido"}, "sql_proibido"),
        (422, {"detail": "LIMIT inválido; use um número inteiro"}, "sql_invalido"),
        (
            422,
            {"detail": "A consulta gerada não pôde ser executada: erro"},
            "execucao_falhou",
        ),
        (400, {"detail": "payload inválido"}, "http_4xx_inesperado"),
    ],
)
def test_taxonomia_http(status, detalhe, esperado):
    assert avaliar_ia._taxonomia_http(status, detalhe, "") == esperado


# =====================================================================
# Login, agregação e relatórios
# =====================================================================
def test_login_devolve_token():
    cliente = ClienteFalso(
        {
            "/api/v1/auth/token/": _resposta(
                200, {"access": "token", "refresh": "refresh"}
            )
        }
    )

    assert avaliar_ia.login(cliente, "demo_admin", "senha") == "token"


def test_login_com_401_vira_erro_auth():
    cliente = ClienteFalso(
        {"/api/v1/auth/token/": _resposta(401, {"detail": "invalido"})}
    )

    with pytest.raises(avaliar_ia.ErroAuth, match="HTTP 401"):
        avaliar_ia.login(cliente, "demo_admin", "senha")


def test_agregar_calcula_taxa_gate_e_falhas():
    resultados = [
        _resultado("1", categoria="contagem", tipo="consulta", sucesso=True),
        _resultado("2", categoria="contagem", tipo="consulta", sucesso=False, falha="sql_proibido"),
        _resultado("3", categoria="join", tipo="consulta", sucesso=True),
        _resultado("4", categoria="rag_tecnico", tipo="rag_tecnico", sucesso=True),
        _resultado("5", categoria="fora_dominio", tipo="recusa_esperada", sucesso=True),
        _resultado("6", categoria="rag_fora_corpus", tipo="guardrail_esperado", sucesso=True),
        _resultado("7", categoria="assist", tipo="assist", sucesso=False, falha="resposta_vazia"),
    ]
    metricas = avaliar_ia.resumir_metricas({})

    resumo = avaliar_ia.agregar(
        resultados,
        min_sucesso=0.8,
        metricas_antes=metricas,
        metricas_depois=metricas,
    )

    assert resumo["total"] == 7
    assert resumo["sucessos"] == 5
    assert resumo["taxa_sucesso"] == pytest.approx(0.7143)
    assert resumo["gate"] == {
        "itens": 4,
        "sucessos": 3,
        "taxa": 0.75,
        "min_sucesso": 0.8,
    }
    assert resumo["falhas_por_tipo"] == {"sql_proibido": 1, "resposta_vazia": 1}
    assert resumo["por_categoria"]["contagem"] == {
        "itens": 2,
        "sucessos": 1,
        "taxa": 0.5,
    }


def test_percentil_interpola():
    valores = [10.0, 20.0, 30.0, 40.0]

    assert avaliar_ia._percentil(valores, 0.50) == 25.0
    assert avaliar_ia._percentil(valores, 0.95) == 38.5
    assert avaliar_ia._percentil([], 0.5) == 0.0


def _metadados() -> dict:
    return {
        "iniciado_em": "2026-11-16T10:00:00+00:00",
        "finalizado_em": "2026-11-16T10:01:00+00:00",
        "duracao_s": 60.0,
        "commit": "abc123",
        "base_url": "http://localhost:8000",
        "modo": "mock",
        "usuario": "demo_admin",
        "golden_set": {
            "caminho": "scripts/avaliacao_ia/golden_set.json",
            "versao": 1,
            "itens": 1,
            "categorias": ["contagem"],
        },
        "metricas_llm": {
            "antes": avaliar_ia.resumir_metricas({}),
            "depois": avaliar_ia.resumir_metricas({}),
        },
    }


def test_gravar_relatorios_gera_json_e_markdown(tmp_path):
    resultado = _resultado("1", categoria="contagem", tipo="consulta", sucesso=True)
    resumo = avaliar_ia.agregar(
        [resultado],
        min_sucesso=0.8,
        metricas_antes=avaliar_ia.resumir_metricas({}),
        metricas_depois=avaliar_ia.resumir_metricas({}),
    )

    json_path, md_path = avaliar_ia.gravar_relatorios(
        saida=tmp_path,
        metadados=_metadados(),
        resumo=resumo,
        resultados=[resultado],
    )

    assert json_path.exists()
    assert md_path.exists()
    relatorio = json.loads(json_path.read_text(encoding="utf-8"))
    assert relatorio["metadados"]["modo"] == "mock"
    assert relatorio["resumo"]["total"] == 1
    assert relatorio["itens"][0]["id"] == "1"
    markdown = md_path.read_text(encoding="utf-8")
    assert "# Avaliação de IA — mock" in markdown
    assert "`contagem`" in markdown
    assert "bearer " not in markdown.lower()


# =====================================================================
# Execução completa com clientes falsos
# =====================================================================
def _cliente_execucao(status_ask_sql: int = 200) -> ClienteFalso:
    dados_ask_sql = {
        "columns": ["total_pedidos"],
        "row_count": 1,
        "rows": [{"total_pedidos": 20}],
        "meta": {"tokens_prompt": 3, "tokens_output": 2, "modelo": "mock-sql"},
    }
    return ClienteFalso(
        {
            "/api/v1/auth/token/": _resposta(200, {"access": "token"}),
            "/api/v1/llm/metrics/": _resposta(
                200,
                {
                    "provedor_configurado": "mock",
                    "provedor_efetivo": "mock",
                    "modelos": {"assist": "mock", "sql": "mock-sql", "docs": "mock-docs"},
                    "total": {
                        "chamadas": 0,
                        "tokens_prompt": 0,
                        "tokens_output": 0,
                        "custo_usd": 0.0,
                        "fallbacks": 0,
                    },
                },
            ),
            "/api/v1/ask_sql/": _resposta(
                status_ask_sql, dados_ask_sql if status_ask_sql == 200 else {"detail": "erro"}
            ),
        }
    )


def test_executar_retorna_0_quando_gate_e_atendido(tmp_path):
    codigo = avaliar_ia.executar(
        golden_set=GOLDEN,
        saida=tmp_path,
        categorias={"contagem"},
        max_questions=1,
        min_sucesso=0.0,
        delay=0.0,
        cliente=_cliente_execucao(),
    )

    assert codigo == 0
    assert list(tmp_path.glob("*.json"))
    assert list(tmp_path.glob("*.md"))


def test_executar_retorna_1_quando_gate_nao_e_atendido(tmp_path):
    codigo = avaliar_ia.executar(
        golden_set=GOLDEN,
        saida=tmp_path,
        categorias={"contagem"},
        max_questions=1,
        min_sucesso=0.9,
        delay=0.0,
        cliente=_cliente_execucao(status_ask_sql=422),
    )

    assert codigo == 1


def test_executar_retorna_3_quando_login_falha(tmp_path):
    cliente = ClienteFalso(
        {"/api/v1/auth/token/": _resposta(401, {"detail": "invalido"})}
    )

    codigo = avaliar_ia.executar(
        golden_set=GOLDEN,
        saida=tmp_path,
        categorias={"contagem"},
        max_questions=1,
        min_sucesso=0.0,
        delay=0.0,
        cliente=cliente,
    )

    assert codigo == 3


def test_executar_retorna_2_sem_itens(tmp_path):
    dados = json.loads(GOLDEN.read_text(encoding="utf-8"))
    dados["itens"] = [item for item in dados["itens"] if item["categoria"] != "assist"]
    caminho = tmp_path / "golden.json"
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")

    codigo = avaliar_ia.executar(
        golden_set=caminho,
        saida=tmp_path,
        categorias={"assist"},
        delay=0.0,
        cliente=_cliente_execucao(),
    )

    assert codigo == 2
