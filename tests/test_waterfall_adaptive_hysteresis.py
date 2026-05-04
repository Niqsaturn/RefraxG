from backend.analysis.waterfall_analyzer import analyze_psd, NoiseFloorTracker, EventHysteresis


def test_adaptive_noise_floor_suppresses_false_positives():
    tracker = NoiseFloorTracker(alpha=0.3)
    # Spiky but mostly noisy; adaptive floor should rise and suppress 1-bin blips.
    psd1 = [-102, -101, -100, -99, -98, -90, -99, -100, -101, -102]
    psd2 = [-101, -100, -99, -98, -97, -89, -98, -99, -100, -101]
    peaks1 = analyze_psd(psd1, 100e6, 2.4e6, min_snr_db=8.0, noise_floor_tracker=tracker, band_key="VHF")
    peaks2 = analyze_psd(psd2, 100e6, 2.4e6, min_snr_db=8.0, noise_floor_tracker=tracker, band_key="VHF")
    assert len(peaks1) <= 1
    assert len(peaks2) <= 1


def test_event_hysteresis_requires_consecutive_frames_and_decays():
    gate = EventHysteresis(required_frames=3, decay_timeout_s=5.0)
    assert gate.observe("evt", 0.0) is False
    assert gate.observe("evt", 1.0) is False
    assert gate.observe("evt", 2.0) is True
    # decay reset
    gate.prune(8.5)
    assert gate.observe("evt", 9.0) is False
