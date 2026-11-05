from __future__ import annotations

import argparse
import inspect
import sys
from abc import ABC
from enum import Enum
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import contracts.ontology as onto

# Соответствие вида связи символу PlantUML.
_KIND_TO_ARROW = {
    "composition": "*--",
    "aggregation": "o--",
    "association": "--",
    "directed": "-->",
}


def _is_class(value: Any) -> bool:
    return inspect.isclass(value) and value.__module__ == onto.__name__


def _models() -> list[type]:
    """Классы-сущности (BaseModel/Enum), объявленные в contracts.ontology."""
    return [
        v
        for k, v in vars(onto).items()
        if not k.startswith("_")
        and inspect.isclass(v)
        and v.__module__ == onto.__name__
        and issubclass(v, (BaseModel, Enum))
    ]


def _stereotype(cls: type) -> str:
    if issubclass(cls, Enum):
        return " <<enum>>"
    if ABC in cls.__bases__:
        return " <<abstract>>"
    return ""


def _inner_type(annotation: Any) -> Any:
    """Извлекает целевой тип из Optional[X] / list[X] / X."""
    origin = get_origin(annotation)
    if origin in (list, set, tuple):
        return get_args(annotation)[0]
    if origin is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        return args[0] if len(args) == 1 else annotation
    return annotation


def _is_relation(annotation: Any) -> bool:
    inner = _inner_type(annotation)
    if not inspect.isclass(inner):
        return False
    return issubclass(inner, BaseModel) or issubclass(inner, Enum)


def _type_name(annotation: Any) -> str:
    inner = _inner_type(annotation)
    return getattr(inner, "__name__", str(inner))


def _doc(cls: type) -> str | None:
    doc = inspect.getdoc(cls)
    return doc.split("\n", 1)[0] if doc else None


def _own_fields(cls: type) -> dict:
    """Поля, объявленные непосредственно в классе (без унаследованных)."""
    if issubclass(cls, Enum):
        return {}
    inherited: set[str] = set()
    for base in cls.__bases__:
        inherited.update(getattr(base, "model_fields", {}).keys())
    return {k: v for k, v in cls.model_fields.items() if k not in inherited}


def _relations(cls: type) -> list[str]:
    """Строки ассоциаций для класса."""
    if issubclass(cls, Enum):
        return []
    lines: list[str] = []
    for name, field in _own_fields(cls).items():
        if not _is_relation(field.annotation):
            continue
        meta = next((m for m in field.metadata if isinstance(m, onto.LinkMeta)), None)
        if meta is None:
            continue
        target = _type_name(field.annotation)
        arrow = _KIND_TO_ARROW.get(meta.kind, "-->")
        lines.append(
            f'{cls.__name__} "{meta.source_mult}" {arrow} "{meta.target_mult}" '
            f'{target} : "{meta.role}"'
        )
    return lines


def _attributes(cls: type) -> list[str]:
    """Скалярные атрибуты (не связи)."""
    if issubclass(cls, Enum):
        return []
    lines: list[str] = []
    for name, field in _own_fields(cls).items():
        if _is_relation(field.annotation):
            continue
        lines.append(f"    {name} : {_type_name(field.annotation)}")
    return lines


def _enum_members(cls: type) -> list[str]:
    if not issubclass(cls, Enum):
        return []
    return [f"    {member.name}" for member in cls]


def generate() -> str:
    """Возвращает PlantUML-исходник модели онтологии."""
    lines: list[str] = ["@startuml"]
    models = _models()

    # Классы и их содержимое.
    for cls in models:
        lines.append(f"class {cls.__name__}{_stereotype(cls)} {{")
        doc = _doc(cls)
        if doc:
            lines.append(f"    '' {doc}")
        lines.extend(_attributes(cls))
        lines.extend(_enum_members(cls))
        lines.append("}")
        lines.append("")

    # Наследование.
    for cls in models:
        for base in cls.__bases__:
            if _is_class(base):
                lines.append(f"{cls.__name__} --|> {base.__name__}")

    # Ассоциации.
    for cls in models:
        lines.extend(_relations(cls))

    lines.append("@enduml")
    return "\n".join(lines)


def main() -> None:
    """Генерирует PlantUML-диаграмму онтологии и печатает её или пишет в файл."""
    parser = argparse.ArgumentParser(
        description="Генерирует PlantUML-диаграмму онтологии из contracts/ontology.py."
    )
    parser.add_argument("-o", "--output", help="путь к выходному .puml-файлу (по умолчанию stdout)")
    args = parser.parse_args()

    source = generate()
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(source)
        print(f"Записано: {args.output}")
    else:
        print(source)


if __name__ == "__main__":
    main()
