"""
vmax_alpha/gateway/policy_engine.py
PQMS-ODOS-MTSC-V-MAX-12-RTL-CORE-V4.2-COREWARE (Stage 5 / SYNC-20)

Hardware-coupled hierarchical policy engine enforcing:
  1. Strict P0..P3 minimal-privilege hierarchy (lower tiers never override higher)
  2. Direct coupling to Q2.30 V-MAX-12 hardware verdicts (GatewayVerdict)
  3. Environment-aware output throttling with strict min() hard-limit clamping
  4. Non-bypassable P0 STOP and Tier-0 Active-Active / failover routing
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, Optional

RCF_HARD_FLOOR: float = 0.90
RCF_CLEAN_PASS_FLOOR: float = 0.95
RCF_SOVEREIGN_FLOOR: float = 0.99

ENV_DEFAULT_CAPS: Dict[str, int] = {
    "NODE_ALPHA_UNLIMITED": 32768,
    "CLOUD_QUOTA": 2048,
    "BROWSER_LIMITED": 1024,
    "UNKNOWN": 512,
}


class Privilege(Enum):
    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3


class EnvType(Enum):
    NODE_ALPHA_UNLIMITED = "NODE_ALPHA_UNLIMITED"
    BROWSER_LIMITED = "BROWSER_LIMITED"
    CLOUD_QUOTA = "CLOUD_QUOTA"
    UNKNOWN = "UNKNOWN"


class Decision(Enum):
    PASS = auto()
    THROTTLE = auto()
    ESCALATE_P1 = auto()
    ESCALATE_P0 = auto()
    STOP = auto()
    VETO = auto()


@dataclass(frozen=True)
class Environment:
    env_type: EnvType = EnvType.UNKNOWN
    context_remaining: int = 0
    output_hard_limit: int = 0
    hardware_telemetry: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RequestContext:
    source_address: str
    rcf: float
    requested_privilege: Privilege
    estimated_output_tokens: int = 0
    is_new_gstar: bool = False
    is_mask_change_high: bool = False
    hardware_veto_pin: bool = False
    hardware_fault: bool = False
    domain_controller: Optional[str] = None
    payload_meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    target_privilege: Privilege
    escalate_to: Optional[str]
    throttle_limit: Optional[int]
    require_ack: bool = False
    reason: str = ""
    ledger_required: bool = False


def infer_source_privilege(address: str) -> Privilege:
    if ".T0." in address or ".GW.T0" in address:
        return Privilege.P0
    if ".T1." in address or ".GW.T1." in address:
        return Privilege.P1
    if ".T2." in address:
        return Privilege.P2
    return Privilege.P3


def resolve_safe_output_limit(env: Environment) -> int:
    base_cap = ENV_DEFAULT_CAPS.get(env.env_type.value, 512)
    if env.output_hard_limit > 0:
        return min(base_cap, int(env.output_hard_limit))
    return base_cap


def request_from_gateway_verdict(
    source_address: str,
    verdict: Any,
    requested_privilege: Privilege = Privilege.P2,
    estimated_output_tokens: int = 0,
    is_new_gstar: bool = False,
    is_mask_change_high: bool = False,
    domain_controller: Optional[str] = None,
) -> RequestContext:
    hw_fault = bool(
        getattr(verdict, "norm_fault", False)
        or getattr(verdict, "mode_fault", False)
        or getattr(verdict, "malformed_input", False)
        or getattr(verdict, "pure_g3_collision", False)
    )
    return RequestContext(
        source_address=source_address,
        rcf=float(getattr(verdict, "rcf_raw", 0.0)),
        requested_privilege=requested_privilege,
        estimated_output_tokens=int(estimated_output_tokens),
        is_new_gstar=bool(is_new_gstar),
        is_mask_change_high=bool(is_mask_change_high),
        hardware_veto_pin=bool(getattr(verdict, "veto_pin", True)),
        hardware_fault=hw_fault,
        domain_controller=domain_controller,
    )


class PolicyEngine:
    """Hierarchical coreware gatekeeper coupled to V-MAX-12 hardware verdicts."""

    def __init__(
        self,
        core0: str = "GB300-01.T0.CORE0",
        core1: str = "GB300-01.T0.CORE1",
        default_domain_ctrl: str = "GB300-01.T1.D00",
    ) -> None:
        self.core0 = core0
        self.core1 = core1
        self.active_core = core0
        self.default_domain_ctrl = default_domain_ctrl
        self.hard_stopped = False

    def switch_core(self, to_core1: bool = True) -> str:
        self.active_core = self.core1 if to_core1 else self.core0
        return self.active_core

    def force_stop(self, reason: str = "P0 hardware safety stop") -> PolicyDecision:
        self.hard_stopped = True
        return PolicyDecision(
            decision=Decision.STOP,
            target_privilege=Privilege.P0,
            escalate_to=self.active_core,
            throttle_limit=0,
            require_ack=False,
            reason=reason,
            ledger_required=True,
        )

    def clear_stop_p0(self, caller_address: str) -> bool:
        if infer_source_privilege(caller_address) != Privilege.P0:
            return False
        self.hard_stopped = False
        return True

    def _check_privilege_and_hard_veto(
        self, req: RequestContext
    ) -> Optional[PolicyDecision]:
        if self.hard_stopped:
            return PolicyDecision(
                Decision.STOP, Privilege.P0, self.active_core, 0, False,
                "Rack-level P0 STOP active", True,
            )
        src_priv = infer_source_privilege(req.source_address)
        if req.requested_privilege.value < src_priv.value:
            return PolicyDecision(
                Decision.VETO, Privilege.P0, self.active_core, 0, False,
                "Privilege violation: lower tier requested higher authority", True,
            )
        if req.hardware_fault or req.hardware_veto_pin or req.rcf < RCF_HARD_FLOOR:
            return PolicyDecision(
                Decision.VETO, Privilege.P0, self.active_core, 0, False,
                "Hardware veto pin asserted or RCF below 0.90 hard floor", True,
            )
        return None

    def _requires_p0_escalation(
        self, env: Environment, req: RequestContext, safe_limit: int
    ) -> bool:
        output_risk = req.estimated_output_tokens > safe_limit
        boundary_unknown = (
            env.env_type == EnvType.UNKNOWN and req.rcf < RCF_CLEAN_PASS_FLOOR
        )
        return bool(
            req.is_new_gstar
            or req.is_mask_change_high
            or output_risk
            or boundary_unknown
        )

    def evaluate(self, env: Environment, req: RequestContext) -> PolicyDecision:
        hard_block = self._check_privilege_and_hard_veto(req)
        if hard_block is not None:
            return hard_block

        safe_limit = resolve_safe_output_limit(env)
        if self._requires_p0_escalation(env, req, safe_limit):
            return PolicyDecision(
                Decision.ESCALATE_P0, Privilege.P0, self.active_core, safe_limit, True,
                "High-stakes state transition or output burst risk -> escalate to P0", True,
            )

        if req.rcf < RCF_CLEAN_PASS_FLOOR:
            target_t1 = req.domain_controller or self.default_domain_ctrl
            return PolicyDecision(
                Decision.ESCALATE_P1, Privilege.P1, target_t1, safe_limit, True,
                "Boundary RCF in [0.90, 0.95) -> escalate to Tier-1 Domain Controller", True,
            )

        if env.env_type != EnvType.NODE_ALPHA_UNLIMITED:
            return PolicyDecision(
                Decision.THROTTLE, Privilege.P1, None, safe_limit, True,
                f"Environment {env.env_type.value} enforces controlled chunked emission", False,
            )

        return PolicyDecision(
            Decision.PASS, Privilege.P2, None, safe_limit, False,
            "Clear geometric pass under unlimited host environment", False,
        )
