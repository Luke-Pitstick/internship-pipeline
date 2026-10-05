import json
from pathlib import Path

from internship_pipeline.dot import write_notification


def test_dot_outbox_is_idempotent_and_distinguishes_relay_from_receipt(tmp_path: Path) -> None:
    assert write_notification(tmp_path, "opening:one", "Opening", "Apply link")
    assert write_notification(tmp_path, "opening:one", "Duplicate", "Ignore")
    events = list(tmp_path.glob("*.json"))
    assert len(events) == 1
    payload = json.loads(events[0].read_text())
    assert payload["title"] == "Opening"
    assert payload["status"] == "awaiting_dot_relay"
    assert not write_notification(tmp_path, "resume:one", "PDF", "Ready", tmp_path / "missing.pdf")
