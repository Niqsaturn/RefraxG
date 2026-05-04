from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app, _run_analysis_cycle
from backend.storage import map_store


def _mk_sample(lat: float, lon: float, bearing: float, idx: int) -> dict:
    return {
        "timestamp": f"2026-05-01T00:00:0{idx}Z",
        "lat": lat,
        "lon": lon,
        "bearing_deg": bearing,
        "heading_deg": bearing,
        "rssi_dbm": -62.0,
        "snr_db": 15.0,
        "frequency_hz": 915000000.0,
        "bandwidth_hz": 25000.0,
    }


def test_triangulation_persists_estimate_and_speculative(monkeypatch, tmp_path):
    db_path = tmp_path / "map_store.db"
    monkeypatch.setattr(map_store, "DB_PATH", db_path)

    samples = [
        _mk_sample(37.7800, -122.4200, 45.0, 1),
        _mk_sample(37.7810, -122.4190, 200.0, 2),
        _mk_sample(37.7790, -122.4180, 300.0, 3),
    ]

    class _Result:
        error = None
        raw_response = "ok"
        detections = [
            {
                "id": "sig-1",
                "label": "Test Signal",
                "freq_band": "UHF",
                "confidence": 0.9,
                "bearing_deg": 45.0,
            }
        ]

    monkeypatch.setattr("backend.main.read_jsonl", lambda _p: samples)
    monkeypatch.setattr("backend.main.detect_signals", lambda *args, **kwargs: _Result())
    monkeypatch.setattr("backend.main._apply_ai_correction_loop", lambda detections, samples: (detections, [], {}))
    monkeypatch.setattr("backend.main.speculate_from_detections", lambda *args, **kwargs: [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-122.4194, 37.7795]},
            "properties": {"id": "spec-1", "kind": "speculative", "confidence": 0.92},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-122.4192, 37.7797]},
            "properties": {"id": "est-1", "kind": "estimate", "confidence": 0.88},
        },
    ])

    _run_analysis_cycle({"limit_samples": 50, "provider": "mock", "model": "test"})

    stored = map_store.get_all_features(limit=1000)["features"]
    kinds = {f["properties"]["kind"] for f in stored}
    assert "speculative" in kinds
    assert "estimate" in kinds


def test_api_features_includes_metadata_and_persisted_features(monkeypatch, tmp_path):
    db_path = tmp_path / "map_store.db"
    monkeypatch.setattr(map_store, "DB_PATH", db_path)

    map_store.upsert_feature({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-122.4, 37.7]},
        "properties": {"id": "spec-api", "kind": "speculative", "confidence": 0.8},
    })

    client = TestClient(app)
    payload = client.get("/api/features").json()

    assert payload["type"] == "FeatureCollection"
    assert "generated_at" in payload
    assert payload["total_count"] >= 1
    ids = {f["properties"]["id"] for f in payload["features"]}
    assert "spec-api" in ids


def test_frontend_refresh_sequence_and_metadata_display():
    js = Path("frontend/main.js").read_text(encoding="utf-8")
    assert "async function _deterministicFeatureRefreshSequence" in js
    assert "await refreshSource();" in js
    assert "await refreshSpeculative();" in js
    assert "health.lastFeaturePayloadGeneratedAt = data.generated_at || null;" in js
