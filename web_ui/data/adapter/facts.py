from __future__ import annotations

from .context import UiServices, get_services
from .core import FACT_TYPE_ORDER, resolve_package


# Кнопки «Применить» и «Сбросить фильтры» списка фактов (рис. 2.13).
def list_facts(
    package: str | None = None,
    type_key: str = "все",
    status: str = "все",
    min_conf: str = "",
    q: str = "",
    *,
    services: UiServices | None = None,
) -> list[dict]:
    """Факты пакета с фильтрами по типу, статусу, уверенности и тексту."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    rows = services.knowledge.list_facts(package)
    if type_key and type_key != "все":
        rows = [f for f in rows if f["type"] == type_key]
    if status and status != "все":
        rows = [f for f in rows if f["status"] == status]
    if min_conf:
        try:
            rows = [f for f in rows if f["confidence"] >= float(min_conf)]
        except ValueError:
            pass
    if q:
        rows = [f for f in rows if q.lower() in f["title"].lower()]
    rows.sort(key=lambda f: (FACT_TYPE_ORDER.get(f["type"], 99), f["id"]))
    return [dict(f) for f in rows]


# Без кнопки: итоговая строка списка фактов (рис. 2.13).
def facts_total(package: str | None = None, *,
                services: UiServices | None = None) -> int:
    """Число фактов пакета."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    return services.knowledge.facts_total(package)


# Кнопка «К подтверждению (N)» списка фактов (рис. 2.13) - бейдж счётчика.
def pending_count(package: str | None = None, *,
                  services: UiServices | None = None) -> int:
    """Число фактов, ждущих подтверждения."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    return services.knowledge.pending_count(package)


# Без кнопки: рендеринг столбца «Источник» таблицы фактов (рис. 2.13).
def fact_source_label(fact: dict) -> str:
    """Подпись источника факта."""
    return f'{fact["doc"]}, фрагмент {fact["frag"]}'


# Клик по ссылке источника в таблице фактов (рис. 2.13) - диалог фрагмента.
def get_fact(fid: str, package: str | None = None, *,
             services: UiServices | None = None) -> dict | None:
    """Факт по id или None."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    fact = services.knowledge.get_fact(fid, package)
    return dict(fact) if fact else None


# Диалог фрагмента-источника: клик по ссылке источника (рис. 2.13);
# из графа - кнопка «Перейти к фрагменту-источнику» (рис. 2.15).
def get_fragment(doc: str, frag: int, package: str | None = None, *,
                 services: UiServices | None = None) -> dict | None:
    """Текст фрагмента-источника или None."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    text = services.chunks.get_fragment(package, doc, frag)
    if text is None:
        return None
    return {"doc": doc, "frag": frag, "text": text, "package": package}
