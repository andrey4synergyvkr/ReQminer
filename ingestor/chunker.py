from __future__ import annotations

import hashlib

from contracts.ontology import DocumentChunk

MAX_CHARS = 2000  # лимит размера фрагмента
OVERLAP_CHARS = 200  # перекрытие соседних фрагментов при делении


def _token_estimate(text: str) -> int:
    """Оценка числа токенов (len/4); точный токенайзер - излишество для лимитов."""
    return len(text) // 4


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atoms(text: str) -> list[str]:
    """Разбивает текст на неделимые куски: абзацы; абзац длиннее лимита
    режется по символам окнами, оставляющими место под перекрытие."""
    window = MAX_CHARS - OVERLAP_CHARS - 2
    out: list[str] = []
    for para in text.split("\n\n"):
        if len(para) <= MAX_CHARS:
            out.append(para)
        else:
            out.extend(para[i:i + window] for i in range(0, len(para), window))
    return out


def _split_oversized(text: str) -> list[tuple[str, int]]:
    """Делит длинный текст по абзацам до лимита; возвращает
    (фрагмент, перекрытие с предыдущим) - перекрытие 0 у первого."""
    pieces: list[tuple[str, int]] = []
    buf, overlap = "", 0
    for atom in _atoms(text):
        if buf and len(buf) + len(atom) + 2 > MAX_CHARS:
            pieces.append((buf, overlap))
            tail = buf[-OVERLAP_CHARS:]
            buf, overlap = tail + "\n\n" + atom, len(tail)
        else:
            buf = f"{buf}\n\n{atom}" if buf else atom
    if buf:
        pieces.append((buf, overlap))
    return pieces


def _build_chunks(doc_name: str, pieces: list[tuple[str, int]]) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    offset = 0
    for i, (text, overlap) in enumerate(pieces, start=1):
        chunks.append(
            DocumentChunk(
                id=f"{doc_name}:{i}",
                chunk_index=i,
                content=text,
                content_hash=_content_hash(text),
                start_offset=offset,
                end_offset=offset + len(text),
                token_count=_token_estimate(text),
                overlap_size=overlap or None,
                metadata=None,
            )
        )
        offset += len(text)
    return chunks


def chunk_markdown(doc_name: str, content: str) -> list[DocumentChunk]:
    """Нарезает Markdown-текст на фрагменты: границы по заголовкам '#',
    длинные разделы - по абзацам с перекрытием OVERLAP_CHARS."""
    if not content.strip():
        return []

    lines = content.splitlines()
    bounds = [i for i, line in enumerate(lines) if line.startswith("# ")]

    if bounds:
        # преамбулa до первого заголовка - отдельный фрагмент
        starts = [0] + bounds if bounds[0] > 0 else bounds
        sections = []
        for j, start in enumerate(starts):
            end = bounds[j + 1] if j + 1 < len(bounds) else len(lines)
            sections.append("\n".join(lines[start:end]))
    else:
        sections = [content]

    pieces: list[tuple[str, int]] = []
    for section in sections:
        if len(section) <= MAX_CHARS:
            pieces.append((section, 0))
        else:
            pieces.extend(_split_oversized(section))
    return _build_chunks(doc_name, pieces)


def chunk_plain(doc_name: str, content: str) -> list[DocumentChunk]:
    """Fallback-нарезка форматов без структуры (.txt, .csv): по размеру,
    без учета заголовков, с тем же перекрытием."""
    if not content.strip():
        return []
    if len(content) <= MAX_CHARS:
        return _build_chunks(doc_name, [(content, 0)])
    return _build_chunks(doc_name, _split_oversized(content))
