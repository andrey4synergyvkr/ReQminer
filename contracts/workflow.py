from enum import StrEnum


class PackageStatus(StrEnum):
    """Статус пакета в реестре."""

    RUN = "run"
    CONFIRM = "confirm"
    DONE = "done"
    REJECT = "reject"
    FAILED = "failed"


class RunState(StrEnum):
    """Состояние прогона."""

    WAIT = "wait"
    RUN = "run"
    CONFIRM = "confirm"
    DONE = "done"
    FAILED = "failed"


class StageStatus(StrEnum):
    """Статус этапа конвейера в записи прогона."""

    WAIT = "wait"
    RUN = "run"
    DONE = "done"
    FAILED = "failed"


class Phase(StrEnum):
    """Фаза конвейера в записи прогресса."""

    INGEST = "ingest"
    EXTRACT = "extract"
    PAIRING = "pairing"
    BUILD = "build"


class PairKind(StrEnum):
    """Тип пары-кандидата (вердикт детектора)."""

    CONTRADICTION = "contradiction"
    DUPLICATE = "duplicate"


class PairStatus(StrEnum):
    """Статус пары после решения аналитика."""

    OPEN = "open"
    DUPLICATE = "duplicate"
    CONTRADICTION = "contradiction"
    DISMISS = "dismiss"


class PairAction(StrEnum):
    """Действия формы подтверждения пары."""

    DUPLICATE = "pair_duplicate"
    CONTRADICTION = "pair_contradiction"
    DISMISS = "pair_dismiss"


class FileVerdict(StrEnum):
    """Вердикт приёма файла пакета."""

    OK = "ok"
    REJECT = "reject"


class EdgeType(StrEnum):
    """Типы рёбер Knowledge."""

    CONTAINS = "содержит"
    USES_TERM = "использует термин"
    EXTRACTED_FROM = "извлечен из"
