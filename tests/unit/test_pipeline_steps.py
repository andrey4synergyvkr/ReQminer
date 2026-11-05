from __future__ import annotations

from pathlib import Path

from services.orchestrator import pipeline, runner
from services.orchestrator.progress import PHASE_DEFS


def test_pipeline_table_matches_screen_stages():
    assert [
        (step.service, step.mod) for step in pipeline.PIPELINE_STEPS
    ] == pipeline.STAGE_DEFS
    assert [step.service for step in pipeline.PIPELINE_STEPS] == [
        "Ingestor", "Extractor", "Extractor", "Builder",
    ]
    assert all(callable(step.handler) for step in pipeline.PIPELINE_STEPS)


def test_phases_match_pipeline_steps_and_weights_sum_to_100():
    assert len(PHASE_DEFS) == len(pipeline.PIPELINE_STEPS)
    assert [
        (definition.service, definition.mod) for definition in PHASE_DEFS
    ] == pipeline.STAGE_DEFS
    assert sum(definition.weight for definition in PHASE_DEFS) == 100


def test_runner_is_thin_dispatcher():
    lines = len(Path(runner.__file__).read_text(encoding="utf-8").splitlines())
    assert lines <= 80, f"runner.py: {lines} строк — верните шаги в pipeline"
