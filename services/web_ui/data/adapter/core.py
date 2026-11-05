from __future__ import annotations

from pathlib import Path

from contracts.facts import FACT_TYPE_ORDER, FACT_TYPE_SPECS
from contracts.ontology import LifecycleStatus
from contracts.workflow import PackageStatus
from demo.scenario import DEMO_PACKAGE, DEMO_USER
from services.ingestor.scanner import ALLOWED_FORMATS

from .context import UiServices, get_services

DATA_DIR = Path(__file__).resolve().parents[1]  # services/web_ui/data
UPLOADS_DIR = DATA_DIR / "uploads"

DEFAULT_PACKAGE = DEMO_PACKAGE
USER = DEMO_USER
POLL_SECONDS = 3  # период автообновления формы «Прогресс прогона»

# Направления пакетов (справочник формы приёма).
DIRECTIONS = ["обращение заказчика"]

# Типы документов по справочнику 1.4.1 (для формы приёма пакета).
DOC_TYPES = [
    "техническое задание",
    "запрос на функциональность",
    "фрагмент переписки",
    "не определен",
]

# Справочник типов фактов: ключи и классы онтологии - contracts/facts.py,
# подписи UI - presentation-слой (они не свойство домена).
FACT_TYPE_LABELS = {
    "epic": "Epic",
    "feature": "Feature",
    "us": "User Story",
    "nfr": "NFR",
    "constraint": "Constraint",
    "term": "Term",
    "vision": "Vision",
}
FACT_TYPES: list[dict] = [
    {"key": spec.key, "label": FACT_TYPE_LABELS[spec.key],
     "ontology": spec.ontology}
    for spec in FACT_TYPE_SPECS
]


def fact_type_label(key: str) -> str:
    """Подпись типа факта для интерфейса."""
    return next((t["label"] for t in FACT_TYPES if t["key"] == key), key)


# Статусы фактов - значения LifecycleStatus из онтологии.
FACT_STATUS_LABELS = {
    LifecycleStatus.CONFIRMED.value: "подтвержден",
    LifecycleStatus.PENDING_REVIEW.value: "ожидает подтверждения",
    LifecycleStatus.NEEDS_CLARIFICATION.value: "требует уточнения",
    LifecycleStatus.REJECTED.value: "отклонен",
    LifecycleStatus.DUPLICATE.value: "дубликат",
}
FACT_STATUS_CSS = {
    LifecycleStatus.CONFIRMED.value: "ok",
    LifecycleStatus.PENDING_REVIEW.value: "pending",
    LifecycleStatus.NEEDS_CLARIFICATION.value: "clarify",
    LifecycleStatus.REJECTED.value: "reject",
    LifecycleStatus.DUPLICATE.value: "run",
}

# Подписи статусов пакета - presentation-слой; реестр отдаёт только коды.
PACKAGE_STATUS_LABELS = {
    PackageStatus.RUN.value: "обработка",
    PackageStatus.CONFIRM.value: "подтверждение фактов",
    PackageStatus.DONE.value: "каркас сформирован",
    PackageStatus.REJECT.value: "отклонен",
    PackageStatus.FAILED.value: "прогон упал",
}


# Без кнопки: пакет для экранов без явного выбора (меню «Факты», «Граф»…).
def resolve_package(package: str | None = None, *,
                    services: UiServices | None = None) -> str:
    """Заданный пакет, если он есть в реестре, иначе новейший пакет реестра;
    при пустом реестре - как задан (экраны показывают пустые состояния)."""
    services = services or get_services()
    package = package or DEFAULT_PACKAGE
    if services.registry.get_package(package) is None:
        newest = services.registry.list_packages()
        if newest:
            return newest[0]["id"]
    return package


# Кнопки «Применить» и «Сбросить фильтры» реестра пакетов (рис. 2.10).
def list_packages(direction: str = "все", status: str = "все", q: str = "",
                  *, services: UiServices | None = None) -> list[dict]:
    """Строки реестра с фильтрами; для активных пакетов добавляет процент."""
    services = services or get_services()
    rows = services.registry.list_packages()
    if direction and direction != "все":
        rows = [p for p in rows if p["direction"] == direction]
    if status and status != "все":
        rows = [p for p in rows if p["status"] == status]
    if q:
        rows = [p for p in rows if q.lower() in p["name"].lower()]
    # процент выполнения - производное значение адаптера, схема пакета
    # не меняется: читаем запись прогона только для активных строк
    from .progress_data import progress_percent  # локально: core ↔ progress

    for row in rows:
        if row["status"] == PackageStatus.RUN.value:
            row["progress_percent"] = progress_percent(
                row["id"], services=services
            )
    return rows


# Без кнопки: данные строки для экранов после перехода кнопкой «Открыть».
def get_package(pid: str, *, services: UiServices | None = None) -> dict | None:
    """Пакет по id или None."""
    services = services or get_services()
    return services.registry.get_package(pid)


# Без кнопки: рендеринг столбца статуса реестра (рис. 2.10).
def package_status_label(pkg: dict) -> str:
    """Подпись статуса пакета; для активного прогона добавляет процент."""
    if pkg["status"] == PackageStatus.REJECT:
        return "отклонен: " + (pkg.get("reject_reason") or "недопустимый формат")
    label = PACKAGE_STATUS_LABELS[pkg["status"]]
    percent = pkg.get("progress_percent")
    # реестр показывает движение активного прогона: «обработка · 68 %»
    return f"{label} · {percent} %" if percent is not None else label


# Без кнопки: рендеринг столбца статуса реестра (рис. 2.10).
def package_status_css(pkg: dict) -> str:
    """CSS-класс статуса пакета."""
    return pkg["status"]
