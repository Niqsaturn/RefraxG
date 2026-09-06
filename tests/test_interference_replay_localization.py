from backend.analysis.waterfall_analyzer import associate_anomalies_to_bearings
from backend.analysis.bayes_field import BayesGrid, BearingUpdate


def test_anomaly_bearing_association_produces_uncertainty():
    anomalies = [{"freq_hz": 915_000_000.0, "confidence": 0.8}]
    samples = [
        {"lat": 37.78, "lon": -122.42, "bearing_deg": 45.0, "snr_db": 12.0, "frequency_hz": 915_000_000.0},
        {"lat": 37.79, "lon": -122.41, "bearing_deg": 50.0, "snr_db": 4.0, "frequency_hz": 920_000_000.0},
    ]
    assoc = associate_anomalies_to_bearings(anomalies, samples)
    assert len(assoc) == 1
    assert assoc[0].bearing_deg == 45.0
    assert assoc[0].sigma_deg > 0


def test_replay_geometry_diversity_improves_bayes_peak_probability():
    grid_poor = BayesGrid(37.78, -122.42, radius_km=20, resolution_km=2)
    # clustered headings -> weaker localization
    for _ in range(4):
        grid_poor.update_bearing(BearingUpdate(obs_lat=37.78, obs_lon=-122.42, bearing_deg=45.0, sigma_deg=18.0))
    poor = grid_poor.posterior_geojson(top_k=50)
    poor_peak = max((f["properties"]["probability"] for f in poor["features"]), default=0)

    grid_good = BayesGrid(37.78, -122.42, radius_km=20, resolution_km=2)
    diverse = [(37.78, -122.42, 40.0), (37.79, -122.41, 190.0), (37.77, -122.40, 300.0), (37.775, -122.43, 120.0)]
    for lat, lon, brg in diverse:
        grid_good.update_bearing(BearingUpdate(obs_lat=lat, obs_lon=lon, bearing_deg=brg, sigma_deg=10.0))
    good = grid_good.posterior_geojson(top_k=50)
    good_peak = max((f["properties"]["probability"] for f in good["features"]), default=0)

    assert good_peak > poor_peak
