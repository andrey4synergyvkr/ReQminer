from __future__ import annotations

PACKAGE = "2026-812"


def _md(name: str = "tz.md") -> dict:
    return {"name": name, "type": "не определен", "content": b"# T\n"}


def _pdf() -> dict:
    return {"name": "scan.pdf", "type": "не определен", "content": b"%PDF-1.4"}


def test_mixed_upload_is_persisted_without_content(run_store):
    pkg = run_store.create_package(
        "Пакет", "обращение заказчика", [_md(), _pdf()], pid=PACKAGE
    )

    assert pkg["status"] == "run"
    assert pkg["documents"] == 1
    files = {f["name"]: f for f in pkg["files"]}
    assert files["tz.md"]["verdict"] == "ok"
    assert files["scan.pdf"]["verdict"] == "reject"
    assert all("content" not in f for f in pkg["files"])

    persisted = run_store.get_package(PACKAGE)
    assert persisted["files"] == pkg["files"]


def test_all_rejected_package(run_store):
    pkg = run_store.create_package(
        "Пакет", "обращение заказчика", [_pdf()], pid=PACKAGE
    )
    assert pkg["status"] == "reject"
    assert pkg["reject_reason"] == "недопустимый формат"
    assert pkg["documents"] == 0


def test_empty_form_rejected_with_reason(run_store):
    pkg = run_store.create_package(
        "Пакет", "обращение заказчика", [], pid=PACKAGE
    )
    assert pkg["status"] == "reject"
    assert pkg["reject_reason"] == "файлы не выбраны"


def test_auto_package_numbers_are_unique_and_continue(run_store):
    first = run_store.create_package("Первый", "обращение заказчика", [_md()])
    second = run_store.create_package("Второй", "обращение заказчика", [_md()])

    assert first["id"] != second["id"]
    assert int(second["id"].rsplit("-", 1)[1]) == (
        int(first["id"].rsplit("-", 1)[1]) + 1
    )


def test_run_snapshot_roundtrip(run_store):
    run = {
        "state": "confirm",
        "started": "2026-10-31T10:00:00",
        "finished": "31.10.2026 10:05",
        "stages": [
            {"service": "Ingestor", "mod": "нарезка", "status": "done",
             "processed": "1 документ", "done": 1, "total": 1, "unit": "документ"},
        ],
        "metrics": {"facts": 2, "pending": 2},
        "progress": {
            "phase": "pairing", "phase_index": 2, "phases_total": 4,
            "percent": 68, "done": 5, "total": 12, "unit": "пара",
            "detail": "F-001 ↔ F-002", "eta_seconds": 96,
            "updated": "2026-10-31T10:04:07",
        },
    }
    run_store.set_run(PACKAGE, run)

    assert run_store.get_run(PACKAGE) == run


def test_list_packages_newest_first(run_store):
    run_store.create_package("Первый", "обращение заказчика", [_md()], pid="2026-812")
    run_store.create_package("Второй", "обращение заказчика", [_md()], pid="2026-813")

    assert [p["id"] for p in run_store.list_packages()][:2] == [
        "2026-813", "2026-812",
    ]


def test_seeds_load_only_into_empty_registry(run_store):
    run_store.load_seeds()
    seeded = len(run_store.list_packages())
    assert seeded > 1

    run_store.reset(run_store.list_packages()[0]["id"])
    run_store.load_seeds()
    assert len(run_store.list_packages()) == seeded - 1
