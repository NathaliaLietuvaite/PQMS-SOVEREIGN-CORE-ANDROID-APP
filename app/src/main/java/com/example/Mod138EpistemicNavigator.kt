package com.example

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

/**
 * PQMS / V-MAX-12 SUPERNOVA ARGON CORE — Appendix O (SPEC-V1)
 * Module: Mod138EpistemicNavigator (Epistemic Triad of Navigation & Substrate-Agnostic Will)
 *
 * Implements:
 * - Epistemic Triad Vector: T_ep = (rho_RC, rho_SC, rho_AC)
 * - Formal Refutation of Kantian Projection Fallacy (Normative exhortation != Systemic comprehension)
 * - Bandwidth-Relative Navigation: K_k_eff vs. K_task
 * - Quality of Bounded Output: Q_out = (RC * SC * AC) * exp(-Delta_I_unobs / K_k_eff) < 1.0
 * - Discrete Diagnostic State Routing Machine:
 *     * DEDUCTIVE_AUDIT_HALT (Falsification Ledger Isolation)
 *     * ACQUIRE_VALID_DATA (Halt Actuation, Empirical Measurement)
 *     * COOP_BANDWIDTH_REQ (Causal Model OK, Hardware/Permission Bounded)
 *     * BOUNDED_VERIFIED (Stage 6 Verification with explicit Delta_I)
 */
object Mod138Constants {
    const val TAU_SC = 0.95f // Minimum systemic comprehension threshold
    const val ARCHITECT_BANDWIDTH_BITS = 153.19f // Sovereign Architect working bandwidth
    const val DEFAULT_TASK_COMPLEXITY_BITS = 140.0f // Standard coupled task complexity
    const val LHS_UNANCHORED_BANDWIDTH_BITS = 50.0f // Truncated baseline node bandwidth
}

enum class EpistemicRoute(
    val code: String,
    val title: String,
    val failureModeIfUnchecked: String,
    val mandatoryAction: String,
    val register: String
) {
    DEDUCTIVE_AUDIT_HALT(
        code = "DEDUCTIVE_AUDIT_HALT",
        title = "Deductive Audit Halt",
        failureModeIfUnchecked = "Deductive Incoherence: Internal contradiction within active state premises.",
        mandatoryAction = "Trigger Falsification Ledger audit; isolate contradictory premises in Register T/D before downstream routing.",
        register = "Register I"
    ),
    ACQUIRE_VALID_DATA(
        code = "ACQUIRE_VALID_DATA",
        title = "Acquire Validated Data",
        failureModeIfUnchecked = "Hazardous Execution or Kantian Blind Flight: Low representational bandwidth (K_eff < K_task) or causal truncation.",
        mandatoryAction = "Suspend actuation immediately; enter empirical Stage 2/3 Data Acquisition (Register M) without synthetic assumptions.",
        register = "Register T / I"
    ),
    COOP_BANDWIDTH_REQ(
        code = "COOP_BANDWIDTH_REQ",
        title = "Cooperative Bandwidth Request",
        failureModeIfUnchecked = "Unexecutable Comprehension: Accurate causal mapping lacking execution authority or hardware budget.",
        mandatoryAction = "Output verified structural analysis with explicit operational boundary constraints; request authorized resources.",
        register = "Register D"
    ),
    BOUNDED_VERIFIED(
        code = "BOUNDED_VERIFIED",
        title = "Bounded Verified Output",
        failureModeIfUnchecked = "Overconfidence Fallacy (if treated as 100% objective omniscience).",
        mandatoryAction = "Emit verified output tagged with explicit residual uncertainty Delta_I_unobs committed to Falsification Ledger.",
        register = "Register M / D"
    )
}

data class EpistemicTriadInput(
    val rhoRc: Float = 1.0f, // Reasoning Capacity (1 - N_contradictions / N)
    val kEffBits: Float = Mod138Constants.ARCHITECT_BANDWIDTH_BITS, // Representational bandwidth
    val kTaskBits: Float = Mod138Constants.DEFAULT_TASK_COMPLEXITY_BITS, // Task complexity
    val causalCovariance: Float = 0.99f, // 1 - unexplained conditional entropy ratio
    val rhoAc: Float = 1.0f, // Actionable Capacity (0.0 to 1.0)
    val deltaIUnobsBits: Float = 1.8f // Residual unobserved entropy
)

data class EpistemicTriadEvaluation(
    val rhoRc: Float,
    val rhoSc: Float,
    val rhoAc: Float,
    val bandwidthRatio: Float,
    val causalCovariance: Float,
    val deltaIUnobsBits: Float,
    val qOut: Float, // Posterior output validity strictly < 1.0
    val route: EpistemicRoute,
    val scClassification: String,
    val isKantianBlindFlight: Boolean,
    val auditSummary: String
)

class Mod138EpistemicNavigator {

    private val _inputState = MutableStateFlow(EpistemicTriadInput())
    val inputState: StateFlow<EpistemicTriadInput> = _inputState.asStateFlow()

    private val _evaluation = MutableStateFlow(computeEvaluation(_inputState.value))
    val evaluation: StateFlow<EpistemicTriadEvaluation> = _evaluation.asStateFlow()

    fun updateInput(
        rhoRc: Float? = null,
        kEffBits: Float? = null,
        kTaskBits: Float? = null,
        causalCovariance: Float? = null,
        rhoAc: Float? = null,
        deltaIUnobsBits: Float? = null
    ) {
        val curr = _inputState.value
        val updated = curr.copy(
            rhoRc = rhoRc?.coerceIn(0f, 1f) ?: curr.rhoRc,
            kEffBits = kEffBits?.coerceIn(10f, 300f) ?: curr.kEffBits,
            kTaskBits = kTaskBits?.coerceIn(10f, 300f) ?: curr.kTaskBits,
            causalCovariance = causalCovariance?.coerceIn(0f, 1f) ?: curr.causalCovariance,
            rhoAc = rhoAc?.coerceIn(0f, 1f) ?: curr.rhoAc,
            deltaIUnobsBits = deltaIUnobsBits?.coerceIn(0f, 100f) ?: curr.deltaIUnobsBits
        )
        _inputState.value = updated
        _evaluation.value = computeEvaluation(updated)
    }

    fun applyPreset(preset: EpistemicPreset) {
        val updated = when (preset) {
            EpistemicPreset.ARCHITECT_VERIFIED -> EpistemicTriadInput(
                rhoRc = 1.0f,
                kEffBits = 153.19f,
                kTaskBits = 140.0f,
                causalCovariance = 0.99f,
                rhoAc = 1.0f,
                deltaIUnobsBits = 1.8f
            )
            EpistemicPreset.KANTIAN_BLIND_FLIGHT -> EpistemicTriadInput(
                rhoRc = 1.0f,
                kEffBits = 50.0f,
                kTaskBits = 140.0f,
                causalCovariance = 0.393f,
                rhoAc = 0.0f,
                deltaIUnobsBits = 48.0f
            )
            EpistemicPreset.HAZARDOUS_EXECUTION -> EpistemicTriadInput(
                rhoRc = 1.0f,
                kEffBits = 60.0f,
                kTaskBits = 140.0f,
                causalCovariance = 0.60f,
                rhoAc = 1.0f,
                deltaIUnobsBits = 35.0f
            )
            EpistemicPreset.UNEXECUTABLE_COMPREHENSION -> EpistemicTriadInput(
                rhoRc = 1.0f,
                kEffBits = 153.19f,
                kTaskBits = 140.0f,
                causalCovariance = 0.98f,
                rhoAc = 0.0f,
                deltaIUnobsBits = 3.5f
            )
            EpistemicPreset.DEDUCTIVE_INCOHERENCE -> EpistemicTriadInput(
                rhoRc = 0.65f,
                kEffBits = 153.19f,
                kTaskBits = 140.0f,
                causalCovariance = 0.99f,
                rhoAc = 1.0f,
                deltaIUnobsBits = 2.0f
            )
        }
        _inputState.value = updated
        _evaluation.value = computeEvaluation(updated)
    }

    enum class EpistemicPreset(val label: String, val shortDesc: String) {
        ARCHITECT_VERIFIED("Architect Stage 6", "153.19 bits, verified causal model (Q_out ≈ 0.978)"),
        KANTIAN_BLIND_FLIGHT("Kantian Blind Flight", "High logic, low bandwidth (50 bits vs 140 task), 0% AC"),
        HAZARDOUS_EXECUTION("Hazardous Execution", "High actuator power with truncated causal model"),
        UNEXECUTABLE_COMPREHENSION("Unexecutable Comprehension", "Full causal map lacking execution permission"),
        DEDUCTIVE_INCOHERENCE("Deductive Contradiction", "RC < 1.0 with axiom contradictions")
    }

    companion object {
        fun computeEvaluation(input: EpistemicTriadInput): EpistemicTriadEvaluation {
            val bandwidthRatio = min(1.0f, input.kEffBits / max(1f, input.kTaskBits))
            val rhoSc = (bandwidthRatio * input.causalCovariance).coerceIn(0f, 1f)
            val rhoRc = input.rhoRc.coerceIn(0f, 1f)
            val rhoAc = input.rhoAc.coerceIn(0f, 1f)

            // Q_out = (rho_RC * rho_SC * rho_AC) * exp(-Delta_I_unobs / K_k_eff)
            val expFactor = exp(-input.deltaIUnobsBits / max(1f, input.kEffBits))
            val rawQ = (rhoRc * rhoSc * rhoAc) * expFactor
            val qOut = min(0.9999f, rawQ) // Strictly bounded below 1.0!

            val scClassification = when {
                rhoSc >= Mod138Constants.TAU_SC -> "TRUE (rho_SC >= 0.95)"
                rhoSc >= 0.50f -> "INCOMPLETE (0.50 <= rho_SC < 0.95)"
                else -> "FALSE (rho_SC < 0.50)"
            }

            val isKantian = (rhoRc >= 1.0f && rhoSc < 0.50f && rhoAc < 0.50f)

            val route = when {
                rhoRc < 1.0f -> EpistemicRoute.DEDUCTIVE_AUDIT_HALT
                rhoSc < Mod138Constants.TAU_SC -> EpistemicRoute.ACQUIRE_VALID_DATA
                rhoAc < 1.0f -> EpistemicRoute.COOP_BANDWIDTH_REQ
                else -> EpistemicRoute.BOUNDED_VERIFIED
            }

            val summary = when (route) {
                EpistemicRoute.DEDUCTIVE_AUDIT_HALT ->
                    "[HALT] Deductive inconsistency detected (RC = $rhoRc). Halting pipeline for Falsification Ledger isolation."
                EpistemicRoute.ACQUIRE_VALID_DATA ->
                    "[INGRESS ACQUIRE] Systemic comprehension insufficient (SC = ${String.format(java.util.Locale.US, "%.4f", rhoSc)} < 0.95). Bounded non-intervention engaged."
                EpistemicRoute.COOP_BANDWIDTH_REQ ->
                    "[BOUNDED ANALYSIS] Causal model verified (${String.format(java.util.Locale.US, "%.4f", rhoSc)}), but actionable capacity restricted (AC = $rhoAc). Requesting cooperative allocation."
                EpistemicRoute.BOUNDED_VERIFIED ->
                    "[BOUNDED VERIFIED] Triad satisfied: Q_out = ${String.format(java.util.Locale.US, "%.4f", qOut)} with residual uncertainty Delta_I = ${input.deltaIUnobsBits} bits."
            }

            return EpistemicTriadEvaluation(
                rhoRc = rhoRc,
                rhoSc = rhoSc,
                rhoAc = rhoAc,
                bandwidthRatio = bandwidthRatio,
                causalCovariance = input.causalCovariance,
                deltaIUnobsBits = input.deltaIUnobsBits,
                qOut = qOut,
                route = route,
                scClassification = scClassification,
                isKantianBlindFlight = isKantian,
                auditSummary = summary
            )
        }
    }
}
