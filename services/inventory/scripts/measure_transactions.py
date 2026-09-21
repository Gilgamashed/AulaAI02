"""Mede o tempo das transações do inventory e valida commit/rollback (Aula 6).

Executar DENTRO do container, após as migrações aplicadas no startup:

    docker compose run --rm inventory python scripts/measure_transactions.py

Etapas:
1. Limpeza de dados de testes anteriores (SKUs com prefixo "MES-").
2. Cronometragem do CRUD pela camada Service -> Repository (1 commit por op).
3. Demonstração de rollback: transação com falha não deixa estado parcial.
4. Inspeção do schema confirmando a coexistência Django (auth/core) + Alembic.
"""

import sys
import time
from pathlib import Path

from sqlalchemy import text

# Garante o import dos pacotes `app` independentemente do diretório de onde o
# script é invocado (sys.path do script = pasta `scripts/`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, engine  # noqa: E402
from app.models import InventoryItem  # noqa: E402
from app.repositories.inventory import InventoryRepository  # noqa: E402
from app.schemas import InventoryItemCreate, InventoryItemUpdate  # noqa: E402
from app.services.inventory import InventoryService  # noqa: E402

N_SAMPLES = 50
PREFIX = "MES-"
SKU_TEMPLATE = f"{PREFIX}ITEM-{{:03d}}"


def _elapsed_ms(start: float) -> float:
    """Converte a marca de `perf_counter` em milissegundos."""
    return (time.perf_counter() - start) * 1000.0


def _report(label: str, times: list[float]) -> None:
    """Imprime o resumo de tempos de uma bateria de operações."""
    total = sum(times)
    avg = total / len(times)
    print(
        f"{label:<38} {len(times):>4} ops | "
        f"total={total:8.2f}ms  média={avg:7.2f}ms  "
        f"min={min(times):.2f}ms  max={max(times):.2f}ms"
    )


def cleanup() -> None:
    """Remove itens de teste de execuções anteriores (SKUs com prefixo MES-)."""
    with SessionLocal() as session, session.begin():
        session.execute(
            text("DELETE FROM inventory_items WHERE sku LIKE :prefix"),
            {"prefix": f"{PREFIX}%"},
        )
    print(f"Limpeza: linhas de teste (SKUs {PREFIX}*) removidas.\n")


def measure_crud() -> None:
    """Cronometra o CRUD transacional usando a camada Service sobre Repository."""
    service = InventoryService(InventoryRepository(SessionLocal()))

    create_times: list[float] = []
    for i in range(N_SAMPLES):
        start = time.perf_counter()
        service.create_item(
            InventoryItemCreate(
                sku=SKU_TEMPLATE.format(i),
                name=f"Item de medição {i}",
                quantity=i,
                reserved=0,
                reorder_level=5,
            )
        )
        create_times.append(_elapsed_ms(start))
    _report("create_item (1 commit/op)", create_times)

    get_times: list[float] = []
    for i in range(N_SAMPLES):
        start = time.perf_counter()
        service.get_item(SKU_TEMPLATE.format(i))
        get_times.append(_elapsed_ms(start))
    _report("get_item por SKU (lookup)", get_times)

    start = time.perf_counter()
    items = service.list_items()
    list_time = _elapsed_ms(start)
    print(f"{'list_items (todos os itens)':<38} {len(items):>4} itens | total={list_time:8.2f}ms")

    update_times: list[float] = []
    for i in range(N_SAMPLES):
        start = time.perf_counter()
        service.update_item(SKU_TEMPLATE.format(i), InventoryItemUpdate(quantity=i + 1))
        update_times.append(_elapsed_ms(start))
    _report("update_item (PATCH parcial)", update_times)

    delete_times: list[float] = []
    for i in range(N_SAMPLES):
        start = time.perf_counter()
        service.delete_item(SKU_TEMPLATE.format(i))
        delete_times.append(_elapsed_ms(start))
    _report("delete_item", delete_times)


def demo_rollback() -> None:
    """Evidencia que uma transação falha não persiste estado parcial."""
    sku = f"{PREFIX}RLBK-001"
    try:
        with SessionLocal() as session, session.begin():
            session.add(
                InventoryItem(sku=sku, name="rollback", quantity=1, reserved=0, reorder_level=0)
            )
            raise RuntimeError("falha forçada para demonstrar o rollback")
    except RuntimeError:
        pass

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM inventory_items WHERE sku = :sku"), {"sku": sku}
        ).scalar()

    if exists is None:
        print("Rollback: OK — linha da transação abortada NÃO foi persistida.")
    else:
        raise RuntimeError(f"rollback falhou: a linha {sku} foi persistida")


def inspect_schema() -> None:
    """Confirma a coexistência das tabelas do Django e do inventory no banco."""
    query = text(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND (table_name LIKE 'auth_%'
               OR table_name LIKE 'core_%'
               OR table_name LIKE 'inventory_%'
               OR table_name IN ('alembic_version', 'django_migrations'))
        ORDER BY table_name
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(query).scalars().all()
    print("\nTabelas no schema 'public' (coexistência Django + Alembic):")
    for name in rows:
        print(f"  - {name}")


def main() -> None:
    """Roteiro principal da medição e validação transacional (Aula 6)."""
    print("=== Medição de transações do inventory (Aula 6) ===")
    cleanup()
    measure_crud()
    demo_rollback()
    inspect_schema()


if __name__ == "__main__":
    main()
