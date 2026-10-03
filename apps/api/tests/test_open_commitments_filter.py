"""open_commitments drops work reported done: the closing status and the due dates it closes."""

from apps.api.hive_adapter import drop_closed_commitments


def _c(subject: str, predicate: str, obj: str, valid_from: int) -> dict:
    return {"id": f"{subject}-{predicate}-{valid_from}", "subject": subject, "predicate": predicate, "object": obj, "valid_from": valid_from}


def test_closed_subject_and_status_row_are_dropped():
    rows = [
        _c("UPI Flow", "due", "2026-09-28", 10),
        _c("UPI Flow", "status", "completed", 20),
        _c("PayU Integration", "due", "2026-10-01", 15),
        _c("Offline Mode", "status", "in progress", 5),
    ]
    kept = drop_closed_commitments(rows)
    assert [(r["subject"], r["predicate"]) for r in kept] == [("PayU Integration", "due"), ("Offline Mode", "status")]


def test_due_date_stated_after_completion_stays_open():
    rows = [_c("Retro Notes", "status", "done", 10), _c("Retro Notes", "due", "2026-10-08", 30)]
    assert [r["predicate"] for r in drop_closed_commitments(rows)] == ["due"]
