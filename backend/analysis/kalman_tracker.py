from __future__ import annotations

import json
import math

_PROC_ACC_MPS2 = 0.5
_DEG_PER_M_LAT = 1.0 / 111_320.0


def _m_to_deg_lat(meters: float) -> float:
    return meters * _DEG_PER_M_LAT


def _m_to_deg_lon(meters: float, lat_deg: float) -> float:
    cos_lat = math.cos(math.radians(lat_deg))
    return meters * _DEG_PER_M_LAT / max(cos_lat, 1e-6)


class PositionKalman:
    """Constant-velocity tracker with bearing-only streaming updates."""

    def __init__(self, init_lat: float, init_lon: float, init_uncertainty_m: float = 5_000.0) -> None:
        self.lat = init_lat
        self.lon = init_lon
        self.v_lat = 0.0
        self.v_lon = 0.0
        sigma_lat = _m_to_deg_lat(init_uncertainty_m)
        sigma_lon = _m_to_deg_lon(init_uncertainty_m, init_lat)
        self.P_lat = sigma_lat ** 2
        self.P_lon = sigma_lon ** 2

    def predict(self, dt_seconds: float = 1.0) -> None:
        dt = max(1e-3, float(dt_seconds))
        self.lat += self.v_lat * dt
        self.lon += self.v_lon * dt
        q_m = _PROC_ACC_MPS2 * dt
        self.P_lat += _m_to_deg_lat(q_m) ** 2
        self.P_lon += _m_to_deg_lon(q_m, self.lat) ** 2

    def update(self, meas_lat: float, meas_lon: float, uncertainty_m: float) -> tuple[float, float, float]:
        sigma_lat = _m_to_deg_lat(uncertainty_m)
        sigma_lon = _m_to_deg_lon(uncertainty_m, self.lat)
        r_lat = sigma_lat ** 2
        r_lon = sigma_lon ** 2
        k_lat = self.P_lat / (self.P_lat + r_lat)
        k_lon = self.P_lon / (self.P_lon + r_lon)
        dlat = meas_lat - self.lat
        dlon = meas_lon - self.lon
        self.lat += k_lat * dlat
        self.lon += k_lon * dlon
        self.v_lat = 0.8 * self.v_lat + 0.2 * (dlat)
        self.v_lon = 0.8 * self.v_lon + 0.2 * (dlon)
        self.P_lat = (1.0 - k_lat) * self.P_lat
        self.P_lon = (1.0 - k_lon) * self.P_lon
        unc_m = math.sqrt(self.P_lat + self.P_lon) / _DEG_PER_M_LAT
        return self.lat, self.lon, unc_m

    def update_from_bearing(self, observer_lat: float, observer_lon: float, bearing_deg: float, sigma_deg: float, range_guess_m: float = 1_500.0) -> tuple[float, float, float, tuple[float, float], tuple[float, float]]:
        rad = math.radians(bearing_deg)
        d_north_m = math.cos(rad) * range_guess_m
        d_east_m = math.sin(rad) * range_guess_m
        meas_lat = observer_lat + _m_to_deg_lat(d_north_m)
        meas_lon = observer_lon + _m_to_deg_lon(d_east_m, observer_lat)
        uncertainty_m = max(50.0, range_guess_m * math.radians(max(1.0, sigma_deg)))
        lat, lon, unc_m = self.update(meas_lat, meas_lon, uncertainty_m)
        cov = ((self.P_lat, 0.0), (0.0, self.P_lon))
        vel = (self.v_lat, self.v_lon)
        return lat, lon, unc_m, cov, vel

    def streaming_update(self, frame: dict, dt_seconds: float = 1.0) -> dict:
        self.predict(dt_seconds)
        lat, lon, unc_m, cov, vel = self.update_from_bearing(
            observer_lat=float(frame["observer_lat"]),
            observer_lon=float(frame["observer_lon"]),
            bearing_deg=float(frame["bearing_deg"]),
            sigma_deg=float(frame.get("sigma_deg", 30.0)),
            range_guess_m=float(frame.get("range_guess_m", 1_500.0)),
        )
        return {
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "covariance": cov,
            "velocity": {"v_lat_deg_s": vel[0], "v_lon_deg_s": vel[1]},
            "uncertainty_m": round(unc_m, 2),
        }

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, data: str) -> "PositionKalman":
        inst = cls.__new__(cls)
        inst.__dict__.update(json.loads(data))
        return inst

    @classmethod
    def for_feature(cls, feature_id: str, lat: float, lon: float) -> "PositionKalman":
        from backend.storage.map_store import get_kalman_state
        s = get_kalman_state(feature_id)
        return cls.from_json(s) if s else cls(lat, lon)

    def save(self, feature_id: str) -> None:
        from backend.storage.map_store import set_kalman_state
        set_kalman_state(feature_id, self.to_json())
