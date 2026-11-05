from __future__ import annotations

import re

from contracts.workflow import PairKind

_NUM_WORDS = {
    "один": 1, "одну": 1, "одного": 1, "два": 2, "двух": 2, "три": 3,
    "трёх": 3, "трех": 3, "четыре": 4, "четырёх": 4, "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6, "семь": 7, "семи": 7, "восемь": 8, "девять": 9,
    "десять": 10, "ста": 100,
}
_STOPWORDS = {
    "как", "я", "мы", "хочу", "чтобы", "и", "в", "во", "на", "с", "со",
    "по", "для", "от", "до", "из", "за", "у", "о", "об", "не", "наиболее",
    "менее", "должна", "должно", "должны", "должен", "система", "системы",
    "системе", "системой", "это", "же", "при", "или", "а", "то", "их",
    "его", "ее", "все", "весь", "каждый", "каждое", "каждого", "каждая",
    "каждую", "каждым", "каждых", "каждые",
    # глаголы-связки NFR-формулировок - не признак похожести
    "превышать", "превысить", "превышает", "превышало", "превышения",
    # роли из шаблона пользовательских историй - не признак похожести
    "аналитик", "оператор", "администратор", "руководитель",
}
_PARAM_WORDS = {"срок", "бюджет", "время"}


def _stem(word: str) -> str:
    """Грубая нормализация: первые 4 буквы (экспорт/экспортировать → экспо)."""
    return word[:4] if len(word) > 4 else word


def _numbers(text: str) -> set[int]:
    result = {int(d) for d in re.findall(r"\d+", text)}
    lowered = text.lower()
    # числительные словами - только целиком («ста» внутри «статуса» - не 100)
    result |= {n for w, n in _NUM_WORDS.items() if re.search(rf"\b{w}\b", lowered)}
    return result


def _tokens(text: str) -> set[str]:
    return {
        _stem(w) for w in re.findall(r"[а-яёa-z0-9]+", text.lower())
        if w not in _STOPWORDS and w not in _NUM_WORDS
    } | {str(n) for n in _numbers(text)}


def token_set(text: str) -> set[str]:
    """Значимые токены текста - для предфильтрации пар без повторной
    токенизации одной и той же формулировки."""
    return _tokens(text)


def common_tokens(text_a: str, text_b: str) -> int:
    """Число общих значимых токенов - предфильтрация похожих пар."""
    return len(_tokens(text_a) & _tokens(text_b))


def offline_candidates(text: str) -> list[dict]:
    """Детерминированное извлечение кандидатов по шаблонам формулировок.

    Правила не взаимоисключающие: фрагмент может дать и пользовательскую
    историю, и определение термина (как LLM-режим - несколько кандидатов).
    """
    text = text.strip()
    candidates: list[dict] = []

    m = re.search(r"[Кк]ак\s+[^,]+,\s*я\s+хочу\s+[^.]+", text)
    if m:
        candidates.append({
            "type": "us", "title": m.group(0).strip().rstrip(","),
            "confidence": 0.85,
        })

    m = re.search(
        r"(?:Функциональность|Запрос на функциональность)[:\s]+«?([^»:.]+)»?",
        text,
    )
    if m:
        candidates.append({
            "type": "feature", "title": m.group(1).strip(), "confidence": 0.90,
        })

    m = re.match(r"^([А-ЯЁ][А-ЯЁа-яё\- ]{2,30})\s+—\s+(.+)$", text)
    # определяемый термин короткий («Эпик - …», «Прогон - …»), длинное
    # подлежащее («Срок внедрения системы - …») - уже формулировка требования
    if m and len(m.group(1).split()) <= 2:
        candidates.append({
            "type": "term", "title": m.group(1).strip(), "confidence": 0.95,
            "definition": m.group(2).strip(),
        })

    if re.search(r"Ключевая цель|интеграц|ЭДО", text):
        candidates.append({"type": "epic", "title": text, "confidence": 0.90})

    if re.search(
        r"срок|бюджет|152-ФЗ|Федеральн|только|закрытом контуре|Windows",
        text, re.I,
    ):
        candidates.append({"type": "constraint", "title": text, "confidence": 0.80})

    if re.search(r"время|доступность|шифр|одновременн", text, re.I):
        candidates.append({"type": "nfr", "title": text, "confidence": 0.85})

    if re.search(
        r"цель|ожидает|трассиров|трудозатрат|качеств|масштабирован|сокращени",
        text, re.I,
    ):
        candidates.append({"type": "vision", "title": text, "confidence": 0.85})

    return candidates


def offline_verdict(a: dict, b: dict) -> dict | None:
    """Один параметр с разными числами - противоречие; похожие
    формулировки - дубликат; иначе - не пара."""
    ta, tb = _tokens(a.get("title", "")), _tokens(b.get("title", ""))
    common = ta & tb
    if not common:
        return None
    title_a, title_b = a.get("title", "").lower(), b.get("title", "").lower()
    if (
        len(common) >= 3
        and any(p in title_a for p in _PARAM_WORDS)
        and any(p in title_b for p in _PARAM_WORDS)
        and _numbers(title_a) and _numbers(title_b)
        and _numbers(title_a) != _numbers(title_b)
    ):
        return {"kind": PairKind.CONTRADICTION.value,
                "reason": "указаны разные значения одного параметра"}
    if len(common) / min(len(ta), len(tb)) >= 0.4:
        return {"kind": PairKind.DUPLICATE.value,
                "reason": "совпадающий смысл формулировок"}
    return None
