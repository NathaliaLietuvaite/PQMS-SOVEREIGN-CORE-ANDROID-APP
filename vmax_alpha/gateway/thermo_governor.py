"""
vmax_alpha/gateway/thermo_governor.py
PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.4-COREWARE (SYNC-24 / Stage 6)

Couples hardware geometric dissonance (delta_e_raw) to proactive GPU DVFS
budgets, guards HBM3e stacks below the 85.0 C JEDEC tREFI refresh cliff,
and computes predictive M/D/2 -> CDU warm-water (45 C -> 60 C) exergy recovery.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

WATER_CP_J_KG_K: float = 4184.0
DEAD_STATE_T0_K: float = 293.15
HBM_GUARD_START_C: float = 76.0
HBM_GUARD_CLAMP_C: float = 83.5
HBM_HARD_VETO_C: float = 84.5


@dataclass(frozen=True)
class ThermoAdmissionResult:
    admitted: bool
    status: str
    hbm_alpha: float
    effective_token_cap: int
    dvfs_scale: float


@dataclass(frozen=True)
class CduExergyCommand:
    forecast_power_kw: float
    mass_flow_kg_s: float
    t_in_c: float
    t_out_target_c: float
    exergy_recovered_kw: float


def compute_hbm_alpha(t_hbm_c: float) -> float:
    if t_hbm_c <= HBM_GUARD_START_C:
        return 1.0
    if t_hbm_c >= HBM_GUARD_CLAMP_C:
        return 0.25
    frac = (t_hbm_c - HBM_GUARD_START_C) / (HBM_GUARD_CLAMP_C - HBM_GUARD_START_C)
    return round(1.0 - 0.75 * frac, 4)


class ThermodynamicGovernor:
    """Closed-loop cognitive-thermodynamic admission and warm-water exergy controller."""

    def __init__(
        self,
        t_in_c: float = 45.0,
        t_out_target_c: float = 60.0,
    ) -> None:
        self.t_in_c = float(t_in_c)
        self.t_out_target_c = float(t_out_target_c)

    def evaluate_admission(
        self,
        base_token_cap: int,
        delta_e_raw: float,
        t_hbm_c: float,
    ) -> ThermoAdmissionResult:
        if t_hbm_c >= HBM_HARD_VETO_C:
            return ThermoAdmissionResult(False, "HBM_THERMAL_VETO", 0.0, 0, 0.0)
        alpha = compute_hbm_alpha(t_hbm_c)
        dissonance_scale = 1.0
        if delta_e_raw > 0.025 and t_hbm_c > 74.0:
            dissonance_scale = max(0.25, 1.0 - (delta_e_raw / 0.05))
        combined = round(alpha * dissonance_scale, 4)
        eff_cap = max(64, int(round(base_token_cap * combined)))
        status = "THERMAL_THROTTLED" if combined < 1.0 else "THERMAL_NOMINAL"
        return ThermoAdmissionResult(True, status, alpha, eff_cap, combined)

    def compute_cdu_feedforward(self, forecast_power_kw: float) -> CduExergyCommand:
        p_w = max(0.0, float(forecast_power_kw) * 1000.0)
        delta_t = max(1.0, self.t_out_target_c - self.t_in_c)
        m_dot = p_w / (WATER_CP_J_KG_K * delta_t)
        t_in_k = self.t_in_c + 273.15
        t_out_k = self.t_out_target_c + 273.15
        exergy_w = m_dot * WATER_CP_J_KG_K * ((t_out_k - t_in_k) - DEAD_STATE_T0_K * math.log(t_out_k / t_in_k))
        return CduExergyCommand(
            forecast_power_kw=round(forecast_power_kw, 3),
            mass_flow_kg_s=round(m_dot, 4),
            t_in_c=self.t_in_c,
            t_out_target_c=self.t_out_target_c,
            exergy_recovered_kw=round(exergy_w / 1000.0, 3),
        )
