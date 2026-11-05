from __future__ import annotations

from contracts.pair_rules import (
    CASCADE_RULES,
    PAIR_ACTIONS,
    detector_cascade,
    resolve_pair,
)
from contracts.workflow import PairAction, PairKind


def _fact(fid: str, confidence: float = 0.9,
          status: str = "pending_review") -> dict:
    return {"id": fid, "confidence": confidence, "status": status}


def test_rules_are_table_driven():
    assert set(CASCADE_RULES) == {
        PairKind.CONTRADICTION, PairKind.DUPLICATE,
    }
    assert set(PAIR_ACTIONS) == {
        PairAction.DUPLICATE, PairAction.CONTRADICTION, PairAction.DISMISS,
    }


def test_contradiction_marks_both_facts():
    changes = detector_cascade(
        PairKind.CONTRADICTION, _fact("F-1"), _fact("F-2")
    )
    assert changes == {
        "F-1": "needs_clarification",
        "F-2": "needs_clarification",
    }


def test_duplicate_marks_less_confident_fact():
    changes = detector_cascade(
        PairKind.DUPLICATE,
        _fact("F-1", confidence=0.9),
        _fact("F-2", confidence=0.5),
    )
    assert changes == {"F-2": "duplicate"}


def test_cascade_does_not_downgrade_terminal_status():
    changes = detector_cascade(
        PairKind.CONTRADICTION,
        _fact("F-1", status="confirmed"),
        _fact("F-2"),
    )
    assert changes == {"F-2": "needs_clarification"}

    changes = detector_cascade(
        PairKind.DUPLICATE,
        _fact("F-1", confidence=0.9),
        _fact("F-2", confidence=0.5, status="confirmed"),
    )
    assert changes == {}


def test_unknown_kind_changes_nothing():
    assert detector_cascade("unknown", _fact("F-1"), _fact("F-2")) == {}


def test_unknown_action_is_rejected():
    assert resolve_pair("pair_approve", _fact("F-1"), _fact("F-2")) is None


def test_duplicate_action_confirms_winner():
    resolution = resolve_pair(
        "pair_duplicate",
        _fact("F-1", confidence=0.9),
        _fact("F-2", confidence=0.5),
    )
    assert resolution is not None
    assert resolution.pair_status == "duplicate"
    assert resolution.statuses == {"F-1": "confirmed", "F-2": "duplicate"}
    assert resolution.mark_reviewed is True


def test_dismiss_returns_both_to_pending():
    resolution = resolve_pair("pair_dismiss", _fact("F-1"), _fact("F-2"))
    assert resolution is not None
    assert resolution.pair_status == "dismiss"
    assert resolution.statuses == {
        "F-1": "pending_review",
        "F-2": "pending_review",
    }
    assert resolution.mark_reviewed is False
