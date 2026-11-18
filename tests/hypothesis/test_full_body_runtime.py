"""Full-body preservation through the production SQLite authority."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.authority.authority import connect_knowledge, ChangeKind, DecisionKind


@pytest.mark.parametrize("body", ["0" * 51, "prefix" * 100 + "unique-tail", "Дані\n" * 30])
def test_full_body_survives_publication_and_restart(tmp_path, body):
    database = str(tmp_path / "authority.db")
    store = connect_knowledge(database, "synthetic")
    store.create_page("synthetic", "body-test", "Title", "initial", "worker")
    base = store.page("synthetic", "body-test").revision
    receipt = store.propose("synthetic", "body-test", base, ChangeKind.REPLACE,
                            "Title", body, "worker", [], key="full-body")
    assert receipt is not None
    store.decide("synthetic", receipt.key, DecisionKind.PUBLISH)
    assert store.page("synthetic", "body-test").markdown == body
    reopened = connect_knowledge(database, "synthetic")
    assert reopened.page("synthetic", "body-test").markdown == body
