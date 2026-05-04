from backend.analysis.waterfall_analyzer import extract_interference_signature
from backend.rf.interference_calculator import classify_interference_hypothesis


def test_narrowband_jammer_signature():
    psd = [-95.0] * 128
    for i in range(60, 64):
        psd[i] = -35.0
    sig = extract_interference_signature(psd, sample_rate_hz=2_000_000)
    assert sig.occupied_bandwidth_hz < 120_000
    assert sig.duty_cycle < 0.1


def test_harmonics_signature_spur_spacing():
    psd = [-98.0] * 128
    for i in [20, 36, 52, 68, 84]:
        psd[i] = -40.0
    sig = extract_interference_signature(psd, sample_rate_hz=1_280_000)
    assert sig.spur_spacing_hz > 100_000


def test_broadband_floor_uplift_flatness():
    psd = [-74.0 + ((i % 4) * 0.2) for i in range(128)]
    sig = extract_interference_signature(psd, sample_rate_hz=2_000_000)
    assert sig.spectral_flatness > 0.9


def test_impulsive_bursts_high_kurtosis_or_burst_rate():
    psd = [-100.0] * 256
    for i in [10, 64, 110, 155, 210]:
        psd[i] = -20.0
    sig = extract_interference_signature(psd, sample_rate_hz=2_560_000)
    assert sig.kurtosis > 5.0
    assert sig.burst_rate_hz > 0


def test_classifier_rules_self_vs_external():
    source, conf = classify_interference_hypothesis({
        "array_control_correlation": 0.8,
        "steering_state_changed": True,
    })
    assert source == "self_generated_likely"
    assert conf > 0.6

    source2, conf2 = classify_interference_hypothesis({
        "array_control_correlation": 0.1,
        "external_motion_score": 0.8,
    })
    assert source2 == "external_interferer_likely"
    assert conf2 > 0.6
