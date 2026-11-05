from __future__ import annotations

import tomllib
from dataclasses import dataclass

from contracts.ontology import LifecycleStatus
from services.common import templating

MANIFEST_NAME = "manifest.toml"
TEMPLATE_SET = templating.TemplateSet("services.builder", "templates")


@dataclass(frozen=True)
class DocumentSpec:
    """Запись каталога документов каркаса."""

    id: str
    path: str
    title: str
    group: str
    template: str
    renderer: str = "template"
    type: str | None = None
    empty_reason: str | None = None
    in_outbox_sections: bool = True


def _load() -> tuple[DocumentSpec, ...]:
    data = tomllib.loads(TEMPLATE_SET.read_text(MANIFEST_NAME))
    return tuple(
        DocumentSpec(
            id=item["id"],
            path=item["path"],
            title=item["title"],
            group=item.get("group", ""),
            template=item["template"],
            renderer=item.get("renderer", "template"),
            type=item.get("type"),
            empty_reason=item.get("empty_reason"),
            in_outbox_sections=item.get("in_outbox_sections", True),
        )
        for item in data["documents"]
    )


DOCUMENTS = _load()
DOCUMENTS_BY_PATH = {document.path: document for document in DOCUMENTS}
DOCUMENTS_BY_TYPE = {
    document.type: document for document in DOCUMENTS if document.type
}
# Документы с фактами: отчёт (renderer="report") рендерится отдельно.
TEMPLATE_DOCUMENTS = tuple(
    document for document in DOCUMENTS if document.renderer == "template"
)

# Файл каркаса -> заголовок раздела (порядок каталога = порядок каркаса).
FILE_TITLES: dict[str, str] = {
    document.path: document.title for document in TEMPLATE_DOCUMENTS
}
# Тип факта -> файл каркаса (однозначное отображение, каждый факт ровно
# в одном файле).
TYPE_TO_FILE: dict[str, str] = {
    document.type: document.path
    for document in TEMPLATE_DOCUMENTS if document.type
}
# Файл каркаса -> причина пустого раздела (заглушка в шаблоне документа).
EMPTY_REASONS: dict[str, str] = {
    document.path: document.empty_reason
    for document in TEMPLATE_DOCUMENTS if document.empty_reason
}


def _sections(documents: tuple[DocumentSpec, ...]) -> list[dict]:
    """Разделы экрана «Результаты прогона»: файлы одной группы показываются
    вместе; группа с каталогом в пути - раздел-каталог, иначе раздел-файл."""
    sections: dict[str, dict] = {}
    for document in documents:
        group = document.group
        section = sections.get(group)
        if section is None:
            directory, _, _ = document.path.rpartition("/")
            section = (
                {"title": group, "file": f"{directory}/", "kind": "dir",
                 "files": [], "types": []}
                if directory
                else {"title": group, "file": document.path, "kind": "file",
                      "types": []}
            )
            sections[group] = section
        section["types"].append(document.type)
        if "files" in section:
            section["files"].append(document.path)
    return list(sections.values())


# Группировка файлов каркаса для экрана отчета (рис. 2.16).
OUTBOX_SECTIONS = _sections(
    tuple(d for d in DOCUMENTS if d.in_outbox_sections)
)


# Статусы, исключаемые из каркаса: отклоненные аналитиком факты и
# подтвержденные дубликаты не попадают в документацию.
_EXCLUDED_STATUSES = {
    LifecycleStatus.REJECTED.value,
    LifecycleStatus.DUPLICATE.value,
}


def validate_config() -> None:
    """Проверка manifest.toml на старте: поля, уникальность type и path."""
    if not DOCUMENTS:
        raise RuntimeError("manifest.toml: документы каркаса не заданы")
    ids: list[str] = []
    paths: list[str] = []
    types: list[str] = []
    for document in DOCUMENTS:
        if document.id in ids:
            raise ValueError(f"manifest.toml: id не уникален: {document.id}")
        if document.path in paths:
            raise ValueError(
                f"manifest.toml: путь не уникален: {document.path}"
            )
        if not document.title or not document.template:
            raise ValueError(
                f"manifest.toml: нет title/template у {document.id}"
            )
        if document.renderer not in ("template", "report"):
            raise ValueError(
                f"manifest.toml: неизвестный renderer {document.renderer}"
            )
        if document.renderer == "template":
            if not document.type or not document.group:
                raise ValueError(
                    f"manifest.toml: нет type/group у {document.path}"
                )
            if not document.empty_reason:
                raise ValueError(
                    f"manifest.toml: нет empty_reason у {document.path}"
                )
            types.append(document.type)
        ids.append(document.id)
        paths.append(document.path)
    if len(set(types)) != len(types):
        raise ValueError("manifest.toml: типы фактов не уникальны")
    names = set(TEMPLATE_SET.names())
    missing = [
        document.template for document in DOCUMENTS
        if document.template not in names
    ]
    if missing:
        raise ValueError(
            "manifest.toml: шаблоны не найдены: " + ", ".join(missing)
        )
    # опечатка в плейсхолдере должна падать на старте, а не в документе
    for document in DOCUMENTS:
        if document.renderer == "template":
            TEMPLATE_SET.render(
                document.template,
                title=document.title,
                facts=(),
                empty_reason=document.empty_reason or "",
                generated=None,
            )
        else:
            TEMPLATE_SET.render(
                document.template,
                package="проверка",
                metrics={},
                gaps=None,
                prompt_version=None,
                generated="",
            )


def plan(facts: list[dict]) -> dict[str, dict]:
    """Раскладывает факты по документам каркаса.

    Возвращает {относительный путь: {"title", "facts"}}; все документы
    стандартной структуры присутствуют всегда, без фактов - с пустым
    списком. Факт неизвестного типа в каркас не попадает.
    """
    sections = {
        document.path: {"title": document.title, "facts": []}
        for document in TEMPLATE_DOCUMENTS
    }
    for fact in facts:
        if fact.get("status") in _EXCLUDED_STATUSES:
            continue
        document = DOCUMENTS_BY_TYPE.get(fact.get("type"))
        if document is not None and document.renderer == "template":
            sections[document.path]["facts"].append(fact)
    return sections


def gaps(facts: list[dict]) -> str | None:
    """Пробелы модели: пользовательские истории без критериев приемки."""
    us = [f for f in facts if f.get("type") == "us"]
    without = [f for f in us if not f.get("acceptance")]
    if not without:
        return None
    return f"не заданы критерии приемки для {len(without)} из {len(us)} пользовательских историй"


def gaps_text(facts: list[dict]) -> str:
    """Строка пробелов модели для отображения в интерфейсе."""
    text = gaps(facts)
    return f"Пробелы модели: {text}" if text else "Пробелы модели: не обнаружены"
