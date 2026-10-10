from django.db.models import Avg, Count, Max, Min
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Category, Item, Notificacao, Pagamento, Pedido, validate_sku


def _strip_required(value, label):
    stripped = value.strip()
    if not stripped:
        raise serializers.ValidationError(f"O campo {label} não pode ser vazio.")
    return stripped


class CategorySerializer(serializers.ModelSerializer):
    items_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "items_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "items_count", "created_at", "updated_at"]

    def validate_name(self, value):
        return _strip_required(value, "nome da categoria")


class ItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    sku = serializers.CharField(
        max_length=100,
        validators=[
            UniqueValidator(
                queryset=Item.objects.all(),
                message="Já existe um produto com este SKU.",
            ),
            validate_sku,
        ],
    )

    class Meta:
        model = Item
        fields = [
            "id",
            "name",
            "brand",
            "model",
            "sku",
            "description",
            "price",
            "specifications",
            "warranty_months",
            "category",
            "category_name",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "category_name", "created_at", "updated_at"]

    def validate_name(self, value):
        return _strip_required(value, "nome")

    def validate_brand(self, value):
        return _strip_required(value, "marca")

    def validate_model(self, value):
        return _strip_required(value, "modelo")

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("O preço não pode ser negativo.")
        return value

    def validate_specifications(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "As especificações devem ser um objeto JSON (dict)."
            )
        return value


class CategoryResumoSerializer(serializers.ModelSerializer):
    """Categoria enxuta para embutir em outros payloads.

    Não inclui `items_count` (que só existe quando a queryset é anotada com
    `Count("items")`, como na listagem de categorias): embutir a categoria em
    outro recurso exigiria garantir essa anotação em todas as consultas.
    """

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "created_at", "updated_at"]
        read_only_fields = fields


class ItemResumoSerializer(serializers.ModelSerializer):
    """Item enxuto para as listas de apoio (`mais_caros`, `recentes`)."""

    class Meta:
        model = Item
        fields = ["id", "name", "brand", "model", "sku", "price"]
        read_only_fields = fields


class ItemDetalheSerializer(serializers.ModelSerializer):
    """Consulta **pesada** de um produto (Aula 8) — fonte do cache `detalhes`.

    O `GET /api/v1/items/{id}/` sozinho é um `SELECT` por PK (o filtro de
    listagem não se aplica). Já o detalhe de negócio precisa cruzar a
    categoria do produto:

    * `SELECT` com `COUNT`/`AVG`/`MIN`/`MAX` sobre os itens da categoria;
    * até 3 itens mais caros da categoria (`ORDER BY price DESC LIMIT 3`);
    * até 3 itens mais recentes (`ORDER BY -created_at LIMIT 3`);
    * a categoria inteira (descrição, slug, datas).

    São 4 consultas por requisição — custo que o cache-aside reduz a um
    `GET` no Redis depois do primeiro acesso. As agregações ficam em
    `SerializerMethodField`: elas só são executadas no **MISS**, já que no
    HIT a resposta vem inteira do cache.
    """

    # `source="category"` é obrigatório: sem ele o DRF buscaria um atributo
    # chamado `categoria` no model (que não existe) e — em silêncio — pularia
    # o campo na resposta (SkipField), em vez de erro.
    categoria = CategoryResumoSerializer(source="category", read_only=True)
    estatisticas_categoria = serializers.SerializerMethodField()
    itens_mais_caros = serializers.SerializerMethodField()
    itens_recentes = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            "id",
            "name",
            "brand",
            "model",
            "sku",
            "description",
            "price",
            "specifications",
            "warranty_months",
            "category",
            "is_active",
            "created_at",
            "updated_at",
            "categoria",
            "estatisticas_categoria",
            "itens_mais_caros",
            "itens_recentes",
        ]
        read_only_fields = fields

    def get_estatisticas_categoria(self, obj: Item) -> dict:
        """Agregados da categoria do item (COUNT/AVG/MIN/MAX de preço)."""
        return obj.category.items.aggregate(
            total_itens=Count("id"),
            preco_medio=Avg("price"),
            preco_minimo=Min("price"),
            preco_maximo=Max("price"),
        )

    def get_itens_mais_caros(self, obj: Item) -> list:
        """Top 3 por preço dentro da mesma categoria do item."""
        return ItemResumoSerializer(
            obj.category.items.order_by("-price", "id")[:3], many=True
        ).data

    def get_itens_recentes(self, obj: Item) -> list:
        """Os 3 itens mais recentes da mesma categoria do produto."""
        return ItemResumoSerializer(
            obj.category.items.order_by("-created_at", "id")[:3], many=True
        ).data


# =====================================================================
# Aula 9 — Pedido
# =====================================================================


class ItemPedidoSerializer(serializers.Serializer):
    """Linha do pedido vinda do cliente: **só o que o cliente decide**.

    O preço unitário NÃO entra no request de propósito. Ele é lido do catálogo
    (`Item.price`) e devolvido na resposta: um cliente que informasse o preço
    poderia trocar um iPhone por R$ 0,01, e o evento `PedidoCriado` — que é o
    que os consumidores vão confiar — carregaria um total inventado.
    """

    sku = serializers.CharField(max_length=100)
    quantidade = serializers.IntegerField(min_value=1, max_value=999)

    def validate_sku(self, value):
        return _strip_required(value, "SKU").upper()


class PedidoCreateSerializer(serializers.Serializer):
    """Entrada do `POST /api/v1/pedidos`.

    Não é um `ModelSerializer` porque dois campos do request **não** são do
    model: a chave de idempotência vem do header `Idempotency-Key` e o
    gancho de falha forçada do header `X-Simular-Falha`. A view monta o
    `Pedido` com o que vem daqui.
    """

    itens = ItemPedidoSerializer(many=True, allow_empty=False)

    def validate_itens(self, value):
        if len(value) > 50:
            raise serializers.ValidationError(
                "Um pedido pode ter no máximo 50 linhas."
            )
        skus = [item["sku"] for item in value]
        duplicados = {sku for sku in skus if skus.count(sku) > 1}
        if duplicados:
            raise serializers.ValidationError(
                f"SKU repetido no pedido: {', '.join(sorted(duplicados))}."
            )
        return value


class PedidoSerializer(serializers.ModelSerializer):
    """Leitura do pedido, já com o estado que o worker persistiu."""

    usuario = serializers.CharField(source="usuario.username", read_only=True)

    class Meta:
        model = Pedido
        fields = [
            "id",
            "usuario",
            "status",
            "itens",
            "total",
            "idempotency_key",
            "tentativas",
            "motivo_falha",
            "created_at",
            "updated_at",
            "processado_em",
        ]
        read_only_fields = fields


# =====================================================================
# Aula 11 — Pagamento e Notificacao
# =====================================================================


class PagamentoSimularSerializer(serializers.Serializer):
    """Entrada do `POST /api/v1/pedidos/{id}/pagamento/`.

    Só o que o **cliente decide** entra aqui, e são duas coisas: o método e o
    desfecho que o gateway deve responder.

    `aprovado` e `motivo_recusa` são a simulação do gateway. Mandá-los no request
    é o que torna a aula demonstrável sem um provedor de verdade: sem eles, o
    único desfecho possível seria "aprovado", e a metade interessante do fluxo
    (recusa, notificação de recusa, re-POST idempotente de um pagamento já
    recusado) ficaria fora da prova.

    `canal` é a escolha de onde o cliente quer ser avisado. Não é coluna do
    `Pagamento`: vive no evento e é copiado para a `Notificacao` pelo worker,
    porque quem **cria** a notificação é o worker, e é ele que precisa do canal.
    """

    metodo = serializers.ChoiceField(choices=Pagamento.METODO_CHOICES)
    aprovado = serializers.BooleanField(
        default=True,
        help_text="Desfecho que o gateway simulado deve responder.",
    )
    motivo_recusa = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        default="",
        help_text="Obrigatório quando 'aprovado' for false.",
    )
    canal = serializers.ChoiceField(
        choices=Notificacao.CANAL_CHOICES,
        default=Notificacao.CANAL_EMAIL,
        required=False,
    )

    def validate(self, attrs):
        """A recusa é um estado consistente, não um texto opcional.

        Mesma regra do contrato `PagamentoRegistrado` (ver
        `contracts.validar_pagamento_registrado`), aplicada já na entrada: é
        melhor um 400 explicando o que falta do que um evento que o worker
        rejeitaria como DLQ por algo que o cliente podia ter lido.
        """
        if not attrs["aprovado"] and not (attrs.get("motivo_recusa") or "").strip():
            raise serializers.ValidationError(
                {
                    "motivo_recusa": (
                        "Obrigatório quando 'aprovado' for false: sem motivo não há "
                        "o que notificar ao cliente."
                    )
                }
            )
        if attrs["aprovado"] and (attrs.get("motivo_recusa") or "").strip():
            raise serializers.ValidationError(
                {
                    "motivo_recusa": (
                        "Não faz sentido com 'aprovado' true — o desfecho e o "
                        "motivo precisam concordar."
                    )
                }
            )
        return attrs


class PagamentoSerializer(serializers.ModelSerializer):
    """Leitura do pagamento, já com o desfecho que o worker persistiu."""

    usuario = serializers.CharField(source="pedido.usuario.username", read_only=True)

    class Meta:
        model = Pagamento
        fields = [
            "id",
            "pedido_id",
            "usuario",
            "metodo",
            "valor",
            "transacao_id",
            "aprovado",
            "motivo_recusa",
            "status",
            "idempotency_key",
            "tentativas",
            "motivo_falha",
            "notificado_em",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class NotificacaoSerializer(serializers.ModelSerializer):
    """Leitura da notificação.

    `pedido_id` vem do FK desnormalizado, e `pagamento_id` permite voltar ao
    pagamento que a originou — é o que o `GET /notificacoes/` precisa mostrar
    para o cliente entender *qual* das cobranças foi avisada.
    """

    class Meta:
        model = Notificacao
        fields = [
            "id",
            "pedido_id",
            "pagamento_id",
            "canal",
            "titulo",
            "mensagem",
            "enviada_em",
        ]
        read_only_fields = fields


# =====================================================================
# Aula 14 — Endpoint de assistência (/api/v1/assist)
# =====================================================================


class AssistSerializer(serializers.Serializer):
    """Entrada do `POST /api/v1/assist`.

    O corpo mínimo da spec é `{ "mode", "logs", "temperature", "max_tokens" }`:

    - `mode` decide a instrução de sistema (sumarizar ou explicar os logs);
    - `logs` aceita **string ou array de strings** (a spec permite os dois) e é
      normalizado para lista — é o que será unido e mandado ao provedor;
    - `temperature` e `max_tokens` controlam a geração; `max_tokens` tem
      padrão 256 e é limitado a 4096 para não queimar tokens num corpo que o
      provedor nem leria.
    """

    MODOS = [("summarize", "summarize"), ("explain", "explain")]

    # Total de caracteres aceitos nos logs: guarda simples de custo — um único
    # request não pode mandar um payload que estoure o orçamento de tokens.
    LOGS_MAX_CARACTERES = 100_000

    mode = serializers.ChoiceField(choices=MODOS)
    logs = serializers.JSONField()
    temperature = serializers.FloatField(
        default=0.2, min_value=0.0, max_value=1.0
    )
    max_tokens = serializers.IntegerField(
        default=256, min_value=1, max_value=4096
    )

    def validate_logs(self, value):
        """Aceita `str` ou `list[str]` e devolve sempre uma lista de textos.

        Um log único chega como string (`"..."`), vários chegam como array
        (`["...", "..."]`). Qualquer outro tipo (número, objeto) é um cliente
        errado: nada aqui é interpretado — o que for enviado vai direto para o
        prompt do provedor.
        """
        if isinstance(value, str):
            textos = [value]
        elif isinstance(value, list):
            textos = value
        else:
            raise serializers.ValidationError(
                "'logs' precisa ser uma string ou uma lista de strings."
            )

        normalizados: list[str] = []
        for texto in textos:
            if not isinstance(texto, str):
                raise serializers.ValidationError(
                    "Cada item de 'logs' precisa ser uma string."
                )
            limpo = texto.strip()
            if not limpo:
                raise serializers.ValidationError(
                    "'logs' não pode conter itens vazios."
                )
            normalizados.append(limpo)

        if not normalizados:
            raise serializers.ValidationError(
                "'logs' não pode ser uma lista vazia: não há o que analisar."
            )

        total = sum(len(t) for t in normalizados)
        if total > self.LOGS_MAX_CARACTERES:
            raise serializers.ValidationError(
                f"'logs' excede o limite de {self.LOGS_MAX_CARACTERES} caracteres."
            )
        return normalizados
