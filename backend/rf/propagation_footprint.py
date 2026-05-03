"""RF propagation footprint geometry.

For every detected or seeded emitter, computes the theoretical maximum range
based on frequency-dependent propagation physics and builds a GeoJSON polygon
suitable for MapLibre rendering.

Propagation modes and ranges grounded in ITU-R documents:
  ELF/SLF/ULF  : Earth-ionosphere waveguide (ITU-R P.684)
  VLF          : Waveguide + ground wave, 3-10 Mm (ITU-R P.684)
  LF           : Ground wave 1-3 Mm (ITU-R P.368)
  MF           : Ground wave 300-800 km; night skywave to 2 Mm
  HF           : Ionospheric skip + skywave; dead zone inside skip distance
  VHF+         : Radio horizon (ITU-R P.526) with k=4/3 effective earth radius
"""
from __future__ import annotations

import logging
import math
from typing import Any

_log = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6_371.0

# ── Maximum theoretical range by frequency ────────────────────────────────
# (upper_freq_hz_exclusive, max_range_km, propagation_label)
_RANGE_TABLE: list[tuple[float, float, str]] = [
    (30,              18_000, "ELF waveguide — global"),
    (300,             16_000, "SLF waveguide — near-global"),
    (3_000,           12_000, "ULF waveguide"),
    (30_000,           8_000, "VLF ionospheric waveguide"),
    (300_000,          3_000, "LF ground wave"),
    (3_000_000,          800, "MF ground wave / night skywave"),
    (30_000_000,      20_000, "HF ionospheric skip + skywave"),  # skip zone added separately
    (300_000_000,        250, "VHF line-of-sight"),
    (3_000_000_000,       60, "UHF line-of-sight"),
    (30_000_000_000,      15, "SHF line-of-sight"),
    (300_000_000_000,      2, "EHF millimetre-wave"),
]
_DEFAULT_RANGE_KM = 1.0

# Band colours for map fill / outline (MapLibre hex)
_BAND_COLORS: list[tuple[float, str]] = [
    (30,               "#6d28d9"),  # ELF   — deep violet
    (3_000,            "#7c3aed"),  # VLF   — violet
    (30_000,           "#8b5cf6"),  # LF    — purple
    (300_000,          "#3b82f6"),  # MF    — blue
    (3_000_000,        "#0ea5e9"),  # HF    — sky blue
    (30_000_000,       "#10b981"),  # VHF   — emerald
    (300_000_000,      "#84cc16"),  # UHF   — lime
    (3_000_000_000,    "#f59e0b"),  # SHF   — amber
    (300_000_000_000,  "#ef4444"),  # EHF   — red
]
_DEFAULT_COLOR = "#6b7280"

# Band name → approximate centre frequency (Hz)
_BAND_NAME_FREQ: dict[str, float] = {
    "elf": 15.0,
    "vlf": 15_000.0,
    "lf": 150_000.0,
    "mf": 1_500_000.0,
    "hf": 15_000_000.0,
    "hf / shortwave": 15_000_000.0,
    "am broadcast": 1_000_000.0,
    "vhf": 150_000_000.0,
    "fm broadcast": 98_000_000.0,
    "aviation vhf": 122_000_000.0,
    "vhf land mobile": 155_000_000.0,
    "uhf": 700_000_000.0,
    "uhf land mobile": 450_000_000.0,
    "cellular / lte": 850_000_000.0,
    "cellular": 850_000_000.0,
    "2.4 ghz": 2_450_000_000.0,
    "5.8 ghz": 5_800_000_000.0,
    "shf": 10_000_000_000.0,
    "ehf": 100_000_000_000.0,
}


# ── Geometry helpers ───────────────────────────────────────────────────────

def _geodesic_ring(lat: float, lon: float, radius_km: float, steps: int = 72) -> list[list[float]]:
    """Closed [lon, lat] ring approximating a geodesic circle."""
    R = EARTH_RADIUS_KM
    d = min(radius_km, R * math.pi * 0.97) / R
    φ1 = math.radians(lat)
    λ1 = math.radians(lon)
    coords: list[list[float]] = []
    for i in range(steps + 1):
        brg = 2 * math.pi * i / steps
        φ2 = math.asin(math.sin(φ1) * math.cos(d) + math.cos(φ1) * math.sin(d) * math.cos(brg))
        λ2 = λ1 + math.atan2(
            math.sin(brg) * math.sin(d) * math.cos(φ1),
            math.cos(d) - math.sin(φ1) * math.sin(φ2),
        )
        coords.append([math.degrees(λ2), math.degrees(φ2)])
    return coords


def _donut_coords(lat: float, lon: float, inner_km: float, outer_km: float, steps: int = 72) -> list[list[list[float]]]:
    """Polygon-with-hole ring coordinates for HF skip zone (outer + reversed inner)."""
    outer = _geodesic_ring(lat, lon, outer_km, steps)
    inner = list(reversed(_geodesic_ring(lat, lon, inner_km, steps)))
    return [outer, inner]


# ── Core lookup helpers ────────────────────────────────────────────────────

def freq_hz_from_band_name(band: str) -> float:
    band_l = band.lower()
    for key, freq in _BAND_NAME_FREQ.items():
        if key in band_l:
            return freq
    return 0.0


def max_range_km(freq_hz: float) -> float:
    for upper, rng, _ in _RANGE_TABLE:
        if freq_hz < upper:
            return rng
    return _DEFAULT_RANGE_KM


def propagation_label(freq_hz: float) -> str:
    for upper, _, label in _RANGE_TABLE:
        if freq_hz < upper:
            return label
    return "unknown"


def band_color(freq_hz: float) -> str:
    for upper, color in _BAND_COLORS:
        if freq_hz <= upper:
            return color
    return _DEFAULT_COLOR


def is_hf(freq_hz: float) -> bool:
    return 3_000_000 <= freq_hz <= 30_000_000


def is_vlf_elf(freq_hz: float) -> bool:
    return freq_hz < 30_000


def is_uwb(freq_hz: float) -> bool:
    return 3_100_000_000 <= freq_hz <= 10_600_000_000


# ── Main footprint builder ─────────────────────────────────────────────────

def compute_footprint(feature: dict[str, Any]) -> dict[str, Any] | None:
    """Return a GeoJSON Feature polygon for the propagation footprint of one emitter.

    For HF: returns a donut polygon (outer = max skywave range, inner = skip dead zone).
    For ELF/VLF: returns a very large circle covering most of the globe.
    For VHF+: returns a circle at the radio-horizon-limited range.
    """
    geom = feature.get("geometry", {})
    props = feature.get("properties", {})
    if geom.get("type") != "Point":
        return None

    lon, lat = geom["coordinates"]

    # Resolve frequency
    freq_hz = float(props.get("frequency_hz") or props.get("freq_hz") or 0)
    if freq_hz <= 0:
        freq_hz = freq_hz_from_band_name(str(props.get("freq_band", "")))
    if freq_hz <= 0:
        return None

    eirp_dbm = float(props.get("eirp_dbm") or props.get("estimated_eirp_dbm") or 46.0)
    feature_id = props.get("id", "")
    color = band_color(freq_hz)
    mode = propagation_label(freq_hz)

    # Compute max range
    max_rng = max_range_km(freq_hz)

    # For VHF+: refine with RSSI-based range if available
    if freq_hz >= 30_000_000:
        rssi = props.get("rssi_dbm")
        if rssi is not None:
            try:
                from backend.analysis.range_estimator import estimate_range_km
                est_km, _ = estimate_range_km(
                    rssi_dbm=float(rssi),
                    freq_mhz=freq_hz / 1e6,
                    snr_db=float(props.get("snr_db") or 10.0),
                    bandwidth_hz=200_000.0,
                    typical_eirp_dbm=eirp_dbm,
                )
                # Take the larger of the physics limit and estimated range
                max_rng = max(max_rng * 0.1, est_km)
            except Exception:
                pass

    skip_km = 0.0

    if is_hf(freq_hz):
        try:
            from backend.rf.rf_propagation import ionospheric_skip_distance_km
            skip_info = ionospheric_skip_distance_km(freq_hz / 1e6)
            skip_km = float(skip_info.get("skip_distance_km", 0.0))
        except Exception:
            skip_km = max_rng * 0.05  # ~5% rough fallback

        if 0 < skip_km < max_rng:
            geom_out = {"type": "Polygon", "coordinates": _donut_coords(lat, lon, skip_km, max_rng)}
        else:
            geom_out = {"type": "Polygon", "coordinates": [_geodesic_ring(lat, lon, max_rng)]}
    else:
        geom_out = {"type": "Polygon", "coordinates": [_geodesic_ring(lat, lon, max_rng)]}

    return {
        "type": "Feature",
        "geometry": geom_out,
        "properties": {
            "feature_id": feature_id,
            "name": props.get("name", ""),
            "freq_hz": freq_hz,
            "freq_mhz": round(freq_hz / 1e6, 4),
            "band_color": color,
            "max_range_km": round(max_rng, 1),
            "skip_km": round(skip_km, 1),
            "mode": mode,
            "is_global": is_vlf_elf(freq_hz),
            "is_hf": is_hf(freq_hz),
            "is_uwb": is_uwb(freq_hz),
            "eirp_dbm": eirp_dbm,
            "kind": props.get("kind", ""),
        },
    }


def build_all_footprints(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Batch-compute propagation footprints for a list of GeoJSON features."""
    results: list[dict[str, Any]] = []
    for f in features:
        try:
            fp = compute_footprint(f)
            if fp:
                results.append(fp)
        except Exception as exc:
            _log.debug("footprint error: %s", exc)
    return results
