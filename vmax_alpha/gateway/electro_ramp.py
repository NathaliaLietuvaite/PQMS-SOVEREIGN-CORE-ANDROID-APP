"""
vmax_alpha/gateway/electro_ramp.py
PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.4-COREWARE (SYNC-24 / Stage 6)

Decouples zero-latency logical quarantine (t = 0.0 us) from slew-rate-bounded
electrical power decay across 8 Tier-1 rack domains (T1.D00..T1.D07), preventing
inductive V = L * dI/dt voltage spikes and cold-plate condensation shock.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

DEFAULT_MAX_SLEW_KW_PER_MS: float = 2.50
DEFAULT_DOMAIN_COUNT: int = 8


@dataclass(frozen=True)
class RampScheduleReport:
    logical_egress_locked: bool
    manifold_write_locked: bool
    logical_lock_latency_us: float
    leaked_tokens_post_veto: int
    initial_power_kw: float
    idle_power_kw: float
    total_ramp_ms: float
    max_slew_kw_per_ms: float
    didt_reduction_factor: float
    domain_steps_ms: Tuple[float, ...]


class ElectroThermalRampController:
    """Slew-rate-bounded 8-domain electrical power ramp coupled to instant P0 STOP."""

    def __init__(
        self,
        max_slew_kw_per_ms: float = DEFAULT_MAX_SLEW_KW_PER_MS,
        domain_count: int = DEFAULT_DOMAIN_COUNT,
    ) -> None:
        self.max_slew_kw_per_ms = max(0.1, float(max_slew_kw_per_ms))
        self.domain_count = max(1, int(domain_count))
        self.logical_egress_locked: bool = False
        self.manifold_write_locked: bool = False

    def trigger_p0_stop_ramp(
        self,
        active_power_kw: float = 120.0,
        idle_power_kw: float = 12.0,
        unbuffered_cutoff_us: float = 2.0,
    ) -> RampScheduleReport:
        self.logical_egress_locked = True
        self.manifold_write_locked = True
        delta_p = max(0.0, float(active_power_kw) - float(idle_power_kw))
        total_ms = delta_p / self.max_slew_kw_per_ms if delta_p > 0.0 else 0.0
        step_ms = total_ms / float(self.domain_count) if total_ms > 0.0 else 0.0
        schedule = tuple(round((i + 1) * step_ms, 3) for i in range(self.domain_count))
        unbuf_ms = max(1e-6, unbuffered_cutoff_us / 1000.0)
        reduction = (total_ms / unbuf_ms) if total_ms > 0.0 else 1.0
        return RampScheduleReport(
            logical_egress_locked=True,
            manifold_write_locked=True,
            logical_lock_latency_us=0.0,
            leaked_tokens_post_veto=0,
            initial_power_kw=round(active_power_kw, 3),
            idle_power_kw=round(idle_power_kw, 3),
            total_ramp_ms=round(total_ms, 3),
            max_slew_kw_per_ms=round(self.max_slew_kw_per_ms, 3),
            didt_reduction_factor=round(reduction, 1),
            domain_steps_ms=schedule,
        )

    def sample_power_trajectory_kw(
        self,
        active_power_kw: float,
        idle_power_kw: float,
        dt_ms: float = 1.0,
    ) -> List[float]:
        rep = self.trigger_p0_stop_ramp(active_power_kw, idle_power_kw)
        if rep.total_ramp_ms <= 0.0:
            return [idle_power_kw]
        n_steps = int(rep.total_ramp_ms / dt_ms) + 2
        trace: List[float] = []
        for k in range(n_steps):
            t_ms = k * dt_ms
            frac = min(1.0, t_ms / rep.total_ramp_ms)
            p_kw = active_power_kw - frac * (active_power_kw - idle_power_kw)
            trace.append(round(p_kw, 4))
        return trace
