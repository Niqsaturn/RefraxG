import time

from fastapi.testclient import TestClient

from backend.main import app
from backend.storage import map_store


def test_startup_migration_readiness_and_features_seeded(monkeypatch, tmp_path):
    db_path = tmp_path / "map_store.db"
    monkeypatch.setattr(map_store, "DB_PATH", db_path)

    seed_feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-96.8, 32.78]},
        "properties": {"id": "seed-startup-1", "kind": "infrastructure", "name": "Seed Site"},
    }
    monkeypatch.setattr("backend.main.load_geojson", lambda: {"type": "FeatureCollection", "features": [seed_feature]})

    with TestClient(app) as client:
        deadline = time.time() + 8
        ready_payload = None
        while time.time() < deadline:
            ready_payload = client.get("/api/health").json()
            if ready_payload.get("map_store_migration_ready"):
                break
            time.sleep(0.2)

        assert ready_payload is not None
        assert ready_payload["map_store_migration_ready"] is True
        assert ready_payload.get("migration_error") is None
        assert ready_payload.get("migrated_count", 0) >= 1

        features = client.get("/api/features").json().get("features", [])
        ids = {f.get("properties", {}).get("id") for f in features}
        assert "seed-startup-1" in ids
        assert len(features) >= 1
