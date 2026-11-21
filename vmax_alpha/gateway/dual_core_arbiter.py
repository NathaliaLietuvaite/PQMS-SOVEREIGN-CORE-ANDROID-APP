"""
vmax_alpha/gateway/dual_core_arbiter.py
PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.3-COREWARE (SYNC-23 / Extension 2)

Deterministic Lockstep & SEU Split-Brain Arbitration for Tier-0 Sovereign Pair:
  - ACTIVE_ACTIVE_SHARDED: 2x throughput with deterministic round-robin sharding
  - LOCKSTEP_DMR_CRITICAL: dual-modular redundant Q2.30 evaluation, any 1-LSB
    mismatch triggers CORE_DIVERGENCE_VETO + inline Known-Answer Test (KAT)
    against frozen Genesis/ROM reference vectors to quarantine the faulty core.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional, Sequence, Tuple


class ArbiterMode(Enum):
    ACTIVE_ACTIVE_SHARDED = auto()
    LOCKSTEP_DMR_CRITICAL = auto()


@dataclass(frozen=True)
class CoreVerdictTuple:
    norm_sq_q: int
    rcf_raw_q: int
    delta_e_raw_q: int
    gate_pass: bool
    veto_pin: bool


@dataclass(frozen=True)
class ArbiterOutcome:
    decision: str
    verdict: Optional[CoreVerdictTuple]
    active_survivor: Optional[str]
    quarantined_core: Optional[str]
    divergence_detected: bool


CoreEvalFn = Callable[[Sequence[int], int], CoreVerdictTuple]


class DualCoreArbiter:
    """Bit-exact SEU split-brain arbiter with inline KAT quarantine."""

    def __init__(
        self,
        core0_fn: CoreEvalFn,
        core1_fn: CoreEvalFn,
        kat_vec_q30: Sequence[int],
        kat_expected: CoreVerdictTuple,
    ) -> None:
        self._core0_fn = core0_fn
        self._core1_fn = core1_fn
        self._kat_vec = list(kat_vec_q30)
        self._kat_expected = kat_expected
        self.core0_healthy: bool = True
        self.core1_healthy: bool = True
        self._rr_toggle: int = 0

    def _run_kat(self) -> Tuple[bool, bool]:
        c0_ok = self._core0_fn(self._kat_vec, 0) == self._kat_expected
        c1_ok = self._core1_fn(self._kat_vec, 0) == self._kat_expected
        return c0_ok, c1_ok

    def _arbitrate_divergence(
        self, v0: CoreVerdictTuple, v1: CoreVerdictTuple
    ) -> ArbiterOutcome:
        c0_ok, c1_ok = self._run_kat()
        self.core0_healthy = c0_ok
        self.core1_healthy = c1_ok
        if c0_ok and not c1_ok:
            return ArbiterOutcome("FAILOVER_TO_CORE0", v0, "GB300-01.T0.CORE0", "GB300-01.T0.CORE1", True)
        if c1_ok and not c0_ok:
            return ArbiterOutcome("FAILOVER_TO_CORE1", v1, "GB300-01.T0.CORE1", "GB300-01.T0.CORE0", True)
        return ArbiterOutcome("CORE_DIVERGENCE_VETO", None, None, "BOTH_CORES", True)

    def evaluate(
        self,
        vec_q30: Sequence[int],
        tier_mode: int = 0,
        mode: ArbiterMode = ArbiterMode.LOCKSTEP_DMR_CRITICAL,
    ) -> ArbiterOutcome:
        if not self.core0_healthy and not self.core1_healthy:
            return ArbiterOutcome("CORE_DIVERGENCE_VETO", None, None, "BOTH_CORES", True)

        if self.core0_healthy and not self.core1_healthy:
            return ArbiterOutcome("SINGLE_CORE0_PASS", self._core0_fn(vec_q30, tier_mode), "GB300-01.T0.CORE0", "GB300-01.T0.CORE1", False)
        if self.core1_healthy and not self.core0_healthy:
            return ArbiterOutcome("SINGLE_CORE1_PASS", self._core1_fn(vec_q30, tier_mode), "GB300-01.T0.CORE1", "GB300-01.T0.CORE0", False)

        if mode == ArbiterMode.ACTIVE_ACTIVE_SHARDED:
            return self._evaluate_sharded(vec_q30, tier_mode)
        return self._evaluate_lockstep(vec_q30, tier_mode)

    def _evaluate_sharded(self, vec_q30: Sequence[int], tier_mode: int) -> ArbiterOutcome:
        use_c0 = (self._rr_toggle % 2) == 0
        self._rr_toggle += 1
        fn = self._core0_fn if use_c0 else self._core1_fn
        name = "GB300-01.T0.CORE0" if use_c0 else "GB300-01.T0.CORE1"
        return ArbiterOutcome("SHARDED_PASS", fn(vec_q30, tier_mode), name, None, False)

    def _evaluate_lockstep(self, vec_q30: Sequence[int], tier_mode: int) -> ArbiterOutcome:
        v0 = self._core0_fn(vec_q30, tier_mode)
        v1 = self._core1_fn(vec_q30, tier_mode)
        if v0 == v1:
            return ArbiterOutcome("LOCKSTEP_AGREE", v0, "GB300-01.T0.CORE0+CORE1", None, False)
        return self._arbitrate_divergence(v0, v1)
