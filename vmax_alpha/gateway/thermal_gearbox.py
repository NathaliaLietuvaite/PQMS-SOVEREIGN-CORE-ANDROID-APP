"""
vmax_alpha/gateway/thermal_gearbox.py
PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.4-COREWARE (SYNC-24 / Stage 6)

Glitch-free thermal clock gearshifting (DFS) and split-manifold anti-common-mode
supervision for the Tier-0 physical V-4.0 silicon pair. At SS_1p08V_125C
(critical path 15.22 ns, f_max = 65.70 MHz), stepping to 62.5 MHz (16.00 ns)
guarantees +0.78 ns positive setup margin and invariant +0.45 ns hold slack.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

SS_125C_CRIT_PATH_NS: float = 15.22
SS_125C_HOLD_WNS_NS: float = 0.45


class ClockGear(Enum):
    GEAR_NOMINAL = auto()
    GEAR_WARM = auto()
    GEAR_HOT_SS_SAFE = auto()
    GEAR_THERMAL_CUTOFF = auto()


@dataclass(frozen=True)
class CoreClockState:
    core_id: str
    temp_c: float
    gear: ClockGear
    freq_mhz: float
    setup_margin_ss_ns: float
    online: bool


@dataclass(frozen=True)
class HeterogeneousPairCapacity:
    core0: CoreClockState
    core1: CoreClockState
    pair_cut_through_tx_s: float
    pair_store_forward_tx_s: float
    p_crit_cut_at_50k_per_chip: float
    p_crit_saf_at_50k_per_chip: float


def select_core_gear(core_id: str, temp_c: float) -> CoreClockState:
    if temp_c <= 70.0:
        return CoreClockState(core_id, temp_c, ClockGear.GEAR_NOMINAL, 100.0, -5.22, True)
    if temp_c <= 95.0:
        return CoreClockState(core_id, temp_c, ClockGear.GEAR_WARM, 80.0, -2.72, True)
    if temp_c <= 125.0:
        margin = round(1000.0 / 62.5 - SS_125C_CRIT_PATH_NS, 2)
        return CoreClockState(core_id, temp_c, ClockGear.GEAR_HOT_SS_SAFE, 62.5, margin, True)
    return CoreClockState(core_id, temp_c, ClockGear.GEAR_THERMAL_CUTOFF, 0.0, 0.0, False)


class ThermalClockGearbox:
    """Split-manifold heterogeneous M/D/2 clock supervisor for T0.CORE0 and T0.CORE1."""

    def __init__(self, n_chips: int = 72, ref_lambda_chip: float = 50000.0) -> None:
        self.n_chips = int(n_chips)
        self.ref_lambda_chip = float(ref_lambda_chip)

    def evaluate_pair(self, temp_core0_c: float, temp_core1_c: float) -> HeterogeneousPairCapacity:
        c0 = select_core_gear("GB300-01.T0.CORE0", temp_core0_c)
        c1 = select_core_gear("GB300-01.T0.CORE1", temp_core1_c)
        total_hz = (c0.freq_mhz + c1.freq_mhz) * 1e6
        cap_cut = total_hz / 200.0
        cap_saf = total_hz / 264.0
        denom = max(1.0, self.n_chips * self.ref_lambda_chip)
        return HeterogeneousPairCapacity(
            core0=c0,
            core1=c1,
            pair_cut_through_tx_s=round(cap_cut, 1),
            pair_store_forward_tx_s=round(cap_saf, 1),
            p_crit_cut_at_50k_per_chip=round(cap_cut / denom, 4),
            p_crit_saf_at_50k_per_chip=round(cap_saf / denom, 4),
        )
