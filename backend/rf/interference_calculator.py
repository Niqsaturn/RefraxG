"""RF interference pattern calculator.

Identifies co-channel emitter pairs, computes coherent superposition of their
E-fields on a spatial grid, and returns GeoJSON heatmap points showing zones
of constructive (green) and destructive (red) interference.

Physics:
  E-field at point P from emitter i:  E_i = sqrt(30 * EIRP_W) / d_i
  Combined coherent field:            E_tot = sqrt(E_a² + E_b² + 2·E_a·E_b·cos(Δφ))
  Phase difference:                   Δφ = 2π·|d_a - d_b| / λ

  interference_ratio = E_combined / E_incoherent  (>1 constructive, <1 destructive)
"""
from __future__ import annotations

import logging
import math
from typing import Any

_log = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_000.0
_GRID_N = 25                   # grid points per dimension per pair
_CO_CHANNEL_HZ = 500_000       # max freq delta to be considered co-channel
_MIN_SEPARATION_M = 200        # skip pairs closer than this (likely same emitter)
_MAX_PAIRS = 15                # cap to prevent quadratic blowup on dense maps


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.asin(math.sqrt(max(0.0, a)))


def _e_field_vm(eirp_dbm: float, distance_m: float) -> float:
    """Far-field E-field magnitude (V/m)."""
    distance_m = max(distance_m, 1.0)
    eirp_w = 10 ** ((eirp_dbm - 30) / 10)
    return math.sqrt(30.0 * eirp_w) / distance_m


def _extract_emitters(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pull lat/lon/freq_hz/eirp from GeoJSON features."""
    from backend.rf.propagation_footprint import freq_hz_from_band_name
    emitters = []
    for f in features:
        geom = f.get("geometry", {})
        props = f.get("properties", {})
        if geom.get("type") != "Point":
            continue
        lon, lat = geom["coordinates"]
        freq_hz = float(props.get("frequency_hz") or props.get("freq_hz") or 0)
        if freq_hz <= 0:
            freq_hz = freq_hz_from_band_name(str(props.get("freq_band", "")))
        if freq_hz <= 0:
            continue
        emitters.append({
            "lat": lat, "lon": lon,
            "freq_hz": freq_hz,
            "eirp_dbm": float(props.get("eirp_dbm") or 46.0),
            "id": props.get("id", ""),
            "name": props.get("name", ""),
        })
    return emitters


def compute_interference_zones(
    features: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return GeoJSON Point Features for a coherent interference heatmap.

    Each point has:
      - interference_ratio: >1 constructive, <1 destructive
      - field_strength_dbvm: combined E-field in dB(V/m)
      - freq_hz: frequency of the co-channel pair
    """
    emitters = _extract_emitters(features)
    if len(emitters) < 2:
        return []

    # Find co-channel pairs, sorted by separation (closest = most significant)
    pairs: list[tuple[dict, dict, float]] = []
    for i in range(len(emitters)):
        for j in range(i + 1, len(emitters)):
            a, b = emitters[i], emitters[j]
            if abs(a["freq_hz"] - b["freq_hz"]) > _CO_CHANNEL_HZ:
                continue
            sep_m = _haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
            if sep_m < _MIN_SEPARATION_M:
                continue
            pairs.append((a, b, sep_m))

    pairs.sort(key=lambda x: x[2])
    pairs = pairs[:_MAX_PAIRS]

    if not pairs:
        return []

    points: list[dict[str, Any]] = []

    for emitter_a, emitter_b, sep_m in pairs:
        freq_hz = (emitter_a["freq_hz"] + emitter_b["freq_hz"]) / 2
        wavelength_m = max(3e8 / freq_hz, 0.001)

        # Bounding box expanded by 60% around the pair
        lat_c = (emitter_a["lat"] + emitter_b["lat"]) / 2
        lon_c = (emitter_a["lon"] + emitter_b["lon"]) / 2
        # Half-span in degrees: cover the interference region generously
        lat_span = max(abs(emitter_a["lat"] - emitter_b["lat"]) * 0.8, 0.05)
        lon_span = max(abs(emitter_a["lon"] - emitter_b["lon"]) * 0.8, 0.05)

        lat_lo = lat_c - lat_span
        lat_hi = lat_c + lat_span
        lon_lo = lon_c - lon_span
        lon_hi = lon_c + lon_span

        lat_step = (lat_hi - lat_lo) / _GRID_N
        lon_step = (lon_hi - lon_lo) / _GRID_N

        for gi in range(_GRID_N):
            for gj in range(_GRID_N):
                pt_lat = lat_lo + gi * lat_step
                pt_lon = lon_lo + gj * lon_step

                d_a = _haversine_m(emitter_a["lat"], emitter_a["lon"], pt_lat, pt_lon)
                d_b = _haversine_m(emitter_b["lat"], emitter_b["lon"], pt_lat, pt_lon)

                e_a = _e_field_vm(emitter_a["eirp_dbm"], d_a)
                e_b = _e_field_vm(emitter_b["eirp_dbm"], d_b)

                # Coherent sum (worst-case constructive/destructive based on path diff)
                path_diff_m = abs(d_a - d_b)
                delta_phi = (2 * math.pi * path_diff_m) / wavelength_m
                e_coh = math.sqrt(e_a ** 2 + e_b ** 2 + 2 * e_a * e_b * math.cos(delta_phi))

                e_incoh = math.sqrt(e_a ** 2 + e_b ** 2)
                ratio = e_coh / max(e_incoh, 1e-20)

                field_db = 20 * math.log10(max(e_coh, 1e-12))

                points.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [pt_lon, pt_lat]},
                    "properties": {
                        "interference_ratio": round(min(ratio, 2.0), 4),
                        "field_strength_dbvm": round(field_db, 2),
                        "freq_hz": round(freq_hz),
                        "source_a": emitter_a["id"],
                        "source_b": emitter_b["id"],
                    },
                })

    return points
