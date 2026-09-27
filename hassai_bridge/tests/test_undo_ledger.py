"""Mutation ledger undo — ownership + idempotency."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture()
def memory_db(tmp_path, monkeypatch):
    import database as db_mod
    from core import database as core_db

    core_db.close_all_connections()
    db_path = tmp_path / "hassai.db"
    monkeypatch.setattr(core_db, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    core_db.init_db()
    yield db_path
    core_db.close_all_connections()


@pytest.mark.asyncio
async def test_undo_rejects_other_user_and_is_idempotent(memory_db):
    from core import database as db
    from services import plan_engine as pe

    ledger_id = "mut_owner_aaa"
    db.add_mutation_ledger(
        ledger_id=ledger_id,
        user_id="alice",
        session_id="s1",
        turn_id="t1",
        action={"domain": "light", "service": "turn_off", "targets": ["light.x"]},
        snapshots={"light.x": {"state": "on", "attributes": {}}},
    )

    with patch("services.homeassistant.run_ha_tool", new_callable=AsyncMock) as mock_ha:
        bad = await pe.undo_ledger(ledger_id, user_id="bob")
        assert bad.get("ok") is False
        assert bad.get("error") == "forbidden"
        mock_ha.assert_not_called()

        good = await pe.undo_ledger(ledger_id, user_id="alice")
        assert good.get("ok") is True
        assert mock_ha.await_count == 1

        again = await pe.undo_ledger(ledger_id, user_id="alice")
        assert again.get("ok") is True
        assert again.get("already_undone") is True
        assert mock_ha.await_count == 1
