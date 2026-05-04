import math

from backend.analysis.kalman_tracker import PositionKalman


def test_converging_track_on_moving_platform():
    kf = PositionKalman(37.0, -122.0)
    lat, lon = 37.0, -122.0
    for _ in range(20):
        lat += 0.00005
        lon += 0.00002
        st = kf.streaming_update({
            "observer_lat": lat - 0.001,
            "observer_lon": lon - 0.001,
            "bearing_deg": 45.0,
            "sigma_deg": 8.0,
            "range_guess_m": 200.0,
        })
    assert abs(st["lat"] - lat) < 0.01
    assert abs(st["lon"] - lon) < 0.01


def test_uncertainty_shrinkage_with_diverse_headings():
    kf = PositionKalman(37.0, -122.0)
    uncs = []
    for b in [0, 45, 90, 135, 180, 225, 270, 315]:
        st = kf.streaming_update({
            "observer_lat": 37.0,
            "observer_lon": -122.0,
            "bearing_deg": b,
            "sigma_deg": 5.0,
            "range_guess_m": 500.0,
        })
        uncs.append(st["uncertainty_m"])
    assert uncs[-1] <= uncs[0]


def test_stable_behavior_under_noisy_bearings():
    kf = PositionKalman(37.0, -122.0)
    vals = []
    for i in range(30):
        noisy = 90.0 + math.sin(i) * 25.0
        st = kf.streaming_update({
            "observer_lat": 37.0,
            "observer_lon": -122.0,
            "bearing_deg": noisy,
            "sigma_deg": 20.0,
            "range_guess_m": 1000.0,
        })
        vals.append(st)
    lat_span = max(v["lat"] for v in vals) - min(v["lat"] for v in vals)
    lon_span = max(v["lon"] for v in vals) - min(v["lon"] for v in vals)
    assert lat_span < 0.2
    assert lon_span < 0.2
