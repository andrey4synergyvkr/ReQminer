from pytest_bdd import given, parsers, scenarios, then, when

from services.ingestor.chunker import MAX_CHARS, chunk_markdown, chunk_plain

scenarios("../../features/ingestor/markdown_chunking.feature")


@given(parsers.parse('документ "{doc}" в формате Markdown прочитан'))
def doc_read(inbox, state, doc):
    state["doc"] = doc
    state["content"] = (inbox / "2026-042" / doc).read_text(encoding="utf-8")


@given('документ содержит разделы верхнего уровня с заголовками')
def doc_has_headings(state):
    assert state["content"].lstrip().startswith("# "), "в документе нет заголовков"


@given('один из разделов документа превышает лимит размера фрагмента')
def doc_section_over_limit(state):
    paragraphs = "\n\n".join(f"Абзац {i}: " + "текст " * 30 for i in range(12))
    state["content"] += f"\n# Большой раздел\n\n{paragraphs}\n"
    assert max(len(s) for s in state["content"].split("# ")) > MAX_CHARS


@given(parsers.parse('документ "{doc}" не имеет структуры Markdown'))
def doc_without_structure(inbox, state, doc):
    state["doc"] = doc
    content = "Строка без структуры. " * (MAX_CHARS * 3 // len("Строка без структуры. "))
    (inbox / "2026-042").mkdir(exist_ok=True)
    (inbox / "2026-042" / doc).write_text(content, encoding="utf-8")
    state["content"] = content


@when('Ingestor нарезает документ')
def chunk_document(state):
    state["chunks"] = chunk_markdown(state["doc"], state["content"])


@when(parsers.parse('Ingestor нарезает документ "{doc}"'))
def chunk_unstructured_doc(state, doc):
    state["chunks"] = chunk_plain(doc, state["content"])


@then('ни один фрагмент не пересекает границу раздела верхнего уровня')
def no_chunk_crosses_section_border(state):
    for c in state["chunks"]:
        for line in c.content.splitlines()[1:]:
            assert not line.startswith("# "), (c.id, line)


@then('у каждого фрагмента заполнен chunk_index')
def chunk_index_filled(state):
    indexes = [c.chunk_index for c in state["chunks"]]
    assert indexes == list(range(1, len(state["chunks"]) + 1)), indexes


@then('раздел разделен на несколько фрагментов')
def oversized_section_split(state):
    assert len(state["chunks"]) > 1
    assert all(len(c.content) <= MAX_CHARS for c in state["chunks"])


@then('соседние фрагменты перекрываются на overlap_size символов')
def chunks_have_overlap(state):
    from services.ingestor.chunker import OVERLAP_CHARS

    overlapped = [c for c in state["chunks"] if c.overlap_size]
    assert overlapped, "перекрытия не обнаружены"
    for c in overlapped:
        assert c.overlap_size <= OVERLAP_CHARS
    for prev, cur in zip(state["chunks"], state["chunks"][1:]):
        if cur.overlap_size:
            assert prev.content[-cur.overlap_size:] in cur.content, (prev.id, cur.id)


@then('у каждого фрагмента заполнены start_offset и end_offset')
def offsets_filled(state):
    for c in state["chunks"]:
        assert c.end_offset == c.start_offset + len(c.content), c.id
    for prev, cur in zip(state["chunks"], state["chunks"][1:]):
        assert cur.start_offset == prev.end_offset or cur.overlap_size, (prev.id, cur.id)


@then('вычислен content_hash содержимого фрагмента')
def content_hash_computed(state):
    import hashlib

    for c in state["chunks"]:
        expected = hashlib.sha256(c.content.encode("utf-8")).hexdigest()
        assert c.content_hash == expected, c.id


@then('заполнен token_count')
def token_count_filled(state):
    for c in state["chunks"]:
        assert c.token_count == len(c.content) // 4, c.id


@then('фрагменты нарезаны по размеру без учета заголовков')
def fallback_chunking_by_size(state):
    chunks = state["chunks"]
    assert chunks, "фрагментов нет"
    assert all(len(c.content) <= MAX_CHARS for c in chunks)
