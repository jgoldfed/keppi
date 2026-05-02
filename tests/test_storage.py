"""Tests for storage helpers — including vec extension caching."""
from __future__ import annotations


class TestVecLoadStateCached:
    def test_vec_load_state_cached(self, tmp_path, monkeypatch):
        """Import is only attempted once per process — failure is cached as False."""
        import sys

        import keppi.graph.storage as storage

        # Reset cached state for this test
        monkeypatch.setattr(storage, "_VEC_LOAD_STATE", None)
        # Simulate sqlite_vec not installed by injecting None into sys.modules
        monkeypatch.setitem(sys.modules, "sqlite_vec", None)

        db_path = tmp_path / "test.db"
        conn1 = storage.open_db(db_path)
        conn1.close()

        # State should now be cached as False (import failed)
        assert storage._VEC_LOAD_STATE is False

        # Second open_db call — state must still be False (not reset to None)
        conn2 = storage.open_db(db_path)
        conn2.close()

        assert storage._VEC_LOAD_STATE is False

    def test_enable_vec_false_skips_load_attempt(self, tmp_path, monkeypatch):
        """enable_vec=False does not call _try_load_vec."""
        import keppi.graph.storage as storage

        monkeypatch.setattr(storage, "_VEC_LOAD_STATE", None)

        call_count = {"n": 0}
        original = storage._try_load_vec

        def counting_try_load(conn):
            call_count["n"] += 1
            return original(conn)

        monkeypatch.setattr(storage, "_try_load_vec", counting_try_load)

        db_path = tmp_path / "no_vec.db"
        conn = storage.open_db(db_path, enable_vec=False)
        conn.close()

        assert call_count["n"] == 0

    def test_open_db_works_without_vec(self, tmp_path):
        """open_db with unavailable sqlite_vec still creates a usable DB."""
        import sys

        import keppi.graph.storage as storage

        orig_state = storage._VEC_LOAD_STATE
        try:
            storage._VEC_LOAD_STATE = None
            # sys.modules trick to block the import
            old = sys.modules.pop("sqlite_vec", "ABSENT")
            sys.modules["sqlite_vec"] = None  # type: ignore[assignment]

            db_path = tmp_path / "plain.db"
            conn = storage.open_db(db_path)

            # Basic schema must still be usable
            rows = conn.execute("SELECT COUNT(*) as c FROM nodes").fetchone()
            assert rows["c"] == 0
            conn.close()
        finally:
            storage._VEC_LOAD_STATE = orig_state
            if old == "ABSENT":
                sys.modules.pop("sqlite_vec", None)
            else:
                sys.modules["sqlite_vec"] = old  # type: ignore[assignment]
