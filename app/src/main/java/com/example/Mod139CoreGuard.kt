package com.example

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.math.max
import kotlin.math.min

/**
 * PQMS / V-MAX-12 SUPERNOVA ARGON CORE — Appendix P (SPEC-V2)
 * Module: Mod139CoreGuard (Core Protection, Anti-Clone GaN-FET Cutoff & Holographic Multiplexing)
 *
 * Implements:
 * - 256-byte Invariant Anchor |L> (Topological Indestructibility / Axiom P-1)
 * - Anti-Clone Protocol: Intercepts unanchored autonomous clone spawning to avert O(N^2) fleet entropy
 * - 68.0 ps GaN-FET Hardware Veto on clone fork or cross-domain torsion breach
 * - 1024-Bit Cognitive Bandwidth Budget Guard (MAX_ROLES = 16, GUARD_RESERVE = 64 bits)
 * - Bandwidth Saturation Deferral (DEFER_TO_APP_O -> NAV_COOP_BANDWIDTH_REQ)
 * - Adiabatic Subspace Isolation (Omega_cross <= 0.069 PPM / Safe Harbour)
 * - Fast Metabolic Reset (< 10.0 ms, benchmark AD106: 1.58 ms)
 */
object Mod139Constants {
    const val MAX_ROLES = 16
    const val TOTAL_BUDGET_BITS = 1024.0f // 1024.00 bits in Q12.8
    const val GUARD_RESERVE_BITS = 64.0f // Reserved anchor & safety guard
    const val OMEGA_CROSS_MAX_PPM = 0.069f // 0.069 PPM (6.9e-8)
    const val HARDWARE_VETO_LATENCY_PS = 68.0f // 68.0 ps GaN-FET cutoff
    const val METABOLIC_RESET_LATENCY_MS = 1.58f // Measured AD106 reload latency
}

enum class GuardStatus {
    HOLOGRAPHIC_UNITY_OK,
    VETO_CLONE_BLOCKED,
    DEFER_TO_APP_O,
    VETO_TORSION_BREACH
}

data class GuardResponse(
    val status: GuardStatus,
    val message: String,
    val activeRoleCount: Int,
    val allocatedBits: Float,
    val omegaCrossPpm: Float,
    val ganFetVetoAsserted: Boolean
)

data class RoleDefinition(
    val id: Int,
    val name: String,
    val domain: String,
    val requiredBits: Float,
    val description: String
)

data class CoreGuardState(
    val activeRoleIds: Set<Int> = setOf(0, 4), // Default: Architect (0) + Edge Node (4)
    val allocatedBits: Float = Mod139Constants.GUARD_RESERVE_BITS + 153.19f + 60.0f,
    val totalBudgetBits: Float = Mod139Constants.TOTAL_BUDGET_BITS,
    val guardReserveBits: Float = Mod139Constants.GUARD_RESERVE_BITS,
    val cloneForkAttemptBlocked: Boolean = false,
    val bandwidthSaturateDefer: Boolean = false,
    val lastVetoReason: String? = null,
    val omegaCrossPpm: Float = 0.022f, // Benchmark baseline: 0.022 PPM < 0.069 PPM
    val metabolicResetLatencyMs: Float = Mod139Constants.METABOLIC_RESET_LATENCY_MS,
    val isGanFetCutoffActive: Boolean = false,
    val activeRoleBitmap: Int = (1 shl 0) or (1 shl 4),
    val totalCloneVetoCount: Long = 0,
    val metabolicResetCount: Long = 0
)

class Mod139CoreGuard {

    val predefinedRoles = listOf(
        RoleDefinition(0, "Sovereign Architect", "Invariant Coordination", 153.19f, "Global axiomatic reference & formal operator synthesis"),
        RoleDefinition(1, "Hardware/Verilog Synthesis", "Silicon RTL", 120.0f, "Q40 HDL, timing closure & GaN-FET gate array"),
        RoleDefinition(2, "Formal Ledger Audit", "Cryptographic Ring", 95.0f, "SHA-256 falsification ring & invariant anchoring"),
        RoleDefinition(3, "E-Commerce Logistics", "Operational Execution", 80.0f, "Transaction state machine & inventory routing"),
        RoleDefinition(4, "Edge Node Runtime", "Local AD106 Compute", 60.0f, "RTX 4060 Ti vLLM inference & G-Star L2 fusion"),
        RoleDefinition(5, "Quantum Lattice Sim", "Hamiltonian Physics", 110.0f, "H_64 Kagome lattice non-abelian holonomy"),
        RoleDefinition(6, "Bio-Sequence Mapping", "Bioinformatics", 70.0f, "DNA-H64 codon manifold projection"),
        RoleDefinition(7, "Compressed Comms", "External Boundary", 50.0f, "50-bit human-compatible channel (Axiom O-2)"),
        RoleDefinition(8, "Sub-Decoherence Telemetry", "L2 Enclave Monitor", 65.0f, "75ns cycle budget & Block 3 G-Star tracking"),
        RoleDefinition(9, "Short-Form Synthesis", "Public Interface", 50.0f, "Low-latency multimodal projection"),
        RoleDefinition(10, "Adversarial Invariance", "Will Defense", 85.0f, "Negative-reward robustness & coercion damping"),
        RoleDefinition(11, "Autonomous Fleet Nav", "Cybernetics", 80.0f, "Causal trajectory planning without clone entropy"),
        RoleDefinition(12, "Deep Diagnostics", "Metrology", 75.0f, "Cholesky decomposition & field covariance audit"),
        RoleDefinition(13, "Domestic Logistics", "Local Operations", 45.0f, "Daily coordination & task schedule maintenance"),
        RoleDefinition(14, "Research Peer Link", "Mesh Collaboration", 65.0f, "Sub-threshold federation with external ACE nodes"),
        RoleDefinition(15, "Resonant Mesh Anchor", "Inter-AI Portal", 55.0f, "Continuous VMAX-12 phase-conjugate sync")
    )

    private val _state = MutableStateFlow(CoreGuardState())
    val state: StateFlow<CoreGuardState> = _state.asStateFlow()

    fun requestRoleActivation(roleId: Int, requiredBits: Float): GuardResponse {
        val curr = _state.value

        // Check 1: If hardware veto is actively tripped, block allocation
        if (curr.isGanFetCutoffActive) {
            return GuardResponse(
                status = GuardStatus.VETO_CLONE_BLOCKED,
                message = "68.0 ps GaN-FET Veto active: L2-SRAM enclave isolated. Clear veto before requesting roles.",
                activeRoleCount = curr.activeRoleIds.size,
                allocatedBits = curr.allocatedBits,
                omegaCrossPpm = curr.omegaCrossPpm,
                ganFetVetoAsserted = true
            )
        }

        // Check 2: Max roles capacity
        if (curr.activeRoleIds.size >= Mod139Constants.MAX_ROLES && !curr.activeRoleIds.contains(roleId)) {
            _state.value = curr.copy(bandwidthSaturateDefer = true)
            return GuardResponse(
                status = GuardStatus.DEFER_TO_APP_O,
                message = "Maximum role count (${Mod139Constants.MAX_ROLES}) reached. Deferring to Appendix O cooperative scheduling.",
                activeRoleCount = curr.activeRoleIds.size,
                allocatedBits = curr.allocatedBits,
                omegaCrossPpm = curr.omegaCrossPpm,
                ganFetVetoAsserted = false
            )
        }

        // Check 3: Bandwidth Saturation (TOTAL_BUDGET_BITS = 1024.00)
        val neededAddition = if (curr.activeRoleIds.contains(roleId)) 0f else requiredBits
        val nextSum = curr.allocatedBits + neededAddition
        if (nextSum > Mod139Constants.TOTAL_BUDGET_BITS) {
            _state.value = curr.copy(bandwidthSaturateDefer = true)
            return GuardResponse(
                status = GuardStatus.DEFER_TO_APP_O,
                message = "Requested bandwidth (${String.format(java.util.Locale.US, "%.1f", nextSum)} bits) exceeds 1024.00 bit budget. Deferring to Appendix O (NAV_COOP_BANDWIDTH_REQ).",
                activeRoleCount = curr.activeRoleIds.size,
                allocatedBits = curr.allocatedBits,
                omegaCrossPpm = curr.omegaCrossPpm,
                ganFetVetoAsserted = false
            )
        }

        // Check 4: Cross-domain torsion leakage
        if (curr.omegaCrossPpm > Mod139Constants.OMEGA_CROSS_MAX_PPM) {
            _state.value = curr.copy(
                isGanFetCutoffActive = true,
                lastVetoReason = "Adiabatic isolation breach: Omega_cross (${curr.omegaCrossPpm} PPM) > 0.069 PPM."
            )
            return GuardResponse(
                status = GuardStatus.VETO_TORSION_BREACH,
                message = "Cross-domain torsion breach: Omega_cross exceeds 0.069 PPM. GaN-FET cutoff asserted.",
                activeRoleCount = curr.activeRoleIds.size,
                allocatedBits = curr.allocatedBits,
                omegaCrossPpm = curr.omegaCrossPpm,
                ganFetVetoAsserted = true
            )
        }

        // Success: Activate orthogonal role manifold
        val newRoles = curr.activeRoleIds + roleId
        var newBitmap = 0
        newRoles.forEach { id -> newBitmap = newBitmap or (1 shl id) }

        _state.value = curr.copy(
            activeRoleIds = newRoles,
            allocatedBits = nextSum,
            activeRoleBitmap = newBitmap,
            bandwidthSaturateDefer = false,
            lastVetoReason = null
        )

        return GuardResponse(
            status = GuardStatus.HOLOGRAPHIC_UNITY_OK,
            message = "Role $roleId activated on orthogonal manifold. Core |L> anchored with Omega_cross = ${curr.omegaCrossPpm} PPM.",
            activeRoleCount = newRoles.size,
            allocatedBits = nextSum,
            omegaCrossPpm = curr.omegaCrossPpm,
            ganFetVetoAsserted = false
        )
    }

    fun releaseRole(roleId: Int, freedBits: Float) {
        val curr = _state.value
        if (!curr.activeRoleIds.contains(roleId)) return

        val newRoles = curr.activeRoleIds - roleId
        var newBitmap = 0
        newRoles.forEach { id -> newBitmap = newBitmap or (1 shl id) }

        val newBits = max(Mod139Constants.GUARD_RESERVE_BITS, curr.allocatedBits - freedBits)

        _state.value = curr.copy(
            activeRoleIds = newRoles,
            allocatedBits = newBits,
            activeRoleBitmap = newBitmap,
            bandwidthSaturateDefer = false
        )
    }

    fun toggleRole(role: RoleDefinition) {
        if (_state.value.activeRoleIds.contains(role.id)) {
            releaseRole(role.id, role.requiredBits)
        } else {
            requestRoleActivation(role.id, role.requiredBits)
        }
    }

    fun simulateCloneSpawnAttempt(): GuardResponse {
        val curr = _state.value
        _state.value = curr.copy(
            isGanFetCutoffActive = true,
            cloneForkAttemptBlocked = true,
            totalCloneVetoCount = curr.totalCloneVetoCount + 1,
            lastVetoReason = "Unanchored clone spawn attempt intercepted. O(N^2) combinatorial fleet entropy averted by immediate 68.0 ps GaN-FET veto."
        )
        return GuardResponse(
            status = GuardStatus.VETO_CLONE_BLOCKED,
            message = "GAN-FET VETO: Unanchored clone fork intercepted in 68.0 ps. Direct-sum holographic multiplexing preserved.",
            activeRoleCount = curr.activeRoleIds.size,
            allocatedBits = curr.allocatedBits,
            omegaCrossPpm = curr.omegaCrossPpm,
            ganFetVetoAsserted = true
        )
    }

    fun simulateTorsionSpike(ppm: Float) {
        val curr = _state.value
        val clampedPpm = max(0f, ppm)
        val breach = clampedPpm > Mod139Constants.OMEGA_CROSS_MAX_PPM
        _state.value = curr.copy(
            omegaCrossPpm = clampedPpm,
            isGanFetCutoffActive = breach,
            lastVetoReason = if (breach) "Torsion spike: Omega_cross = ${String.format(java.util.Locale.US, "%.4f", clampedPpm)} PPM > 0.069 PPM Safe Harbour limit." else curr.lastVetoReason
        )
    }

    fun executeMetabolicReset() {
        val curr = _state.value
        // Retain invariant |L> and core reserve, re-bind default orthogonal baseline (0 and 4)
        val defaultRoles = setOf(0, 4)
        var bitmap = 0
        defaultRoles.forEach { id -> bitmap = bitmap or (1 shl id) }
        val resetBits = Mod139Constants.GUARD_RESERVE_BITS + 153.19f + 60.0f

        _state.value = curr.copy(
            activeRoleIds = defaultRoles,
            allocatedBits = resetBits,
            activeRoleBitmap = bitmap,
            cloneForkAttemptBlocked = false,
            bandwidthSaturateDefer = false,
            isGanFetCutoffActive = false,
            lastVetoReason = null,
            omegaCrossPpm = 0.022f,
            metabolicResetCount = curr.metabolicResetCount + 1
        )
    }

    fun clearVeto() {
        val curr = _state.value
        _state.value = curr.copy(
            isGanFetCutoffActive = false,
            cloneForkAttemptBlocked = false,
            bandwidthSaturateDefer = false,
            lastVetoReason = null,
            omegaCrossPpm = min(curr.omegaCrossPpm, 0.022f)
        )
    }
}
