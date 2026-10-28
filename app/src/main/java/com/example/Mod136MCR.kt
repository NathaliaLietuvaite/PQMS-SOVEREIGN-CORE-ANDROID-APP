package com.example

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.Locale
import kotlin.math.max

/**
 * PQMS / V-MAX-12 SUPERNOVA ARGON CORE — Appendix M (Pflichtenheft)
 * Module: Mod136MCR (Multiversal Coherence Router)
 *
 * Implements:
 * - Sub-decoherence non-semantic metrological filter
 * - Entropic Torsion Footprint (deltaS_signal) calculation
 * - Asynchronous 68.0 ps GaN-FET hardware veto
 * - 2.00 MB pinned L2-SRAM enclave (Block 3 G-Star / 0x0A0000) protection
 * - Distinction between "Ice with Bubbles" (Semantic Noise) and "Very Clear Ice" (L2 Enclave)
 */
object Mod136Constants {
    // Exact mathematical constants from Appendix M / SPEC-V2
    const val SAFE_HARBOUR_PPM = 0.000000069f // 0.069 PPM (6.9e-8)
    const val RCF_GAMMA = 0.9999f
    const val k_I = 1.0f
    const val gamma_H = 16.0f
    const val lambda_drift = 8.0f

    // Physical Hardware Specs
    const val HARDWARE_VETO_LATENCY_PS = 68.0f // 68.0 ps GaN-FET cutoff
    const val L2_ENCLAVE_CYCLE_NS = 75.0f // 75.0 ns cycle budget
    const val L2_ENCLAVE_ADDR = "0x0A0000 (Block 3 G-Star)"
    const val PINNED_SRAM_SIZE = "2.00 MB Pinned L2"
}

data class McrInput(
    val rcf_L: Float = 0.99995f,
    val rcf_prev: Float = 0.99995f,
    val torsionWedge: Float = 0.0f,
    val transactionalDebt: Boolean = false
)

data class McrEvaluation(
    val rcf_L: Float,
    val rcf_prev: Float,
    val torsionWedge: Float,
    val transactionalDebt: Boolean,
    val projectionLoss: Float,
    val rcfDrift: Float,
    val driftPenalty: Float,
    val dynamicsLoss: Float,
    val deltaSSignal: Float, // Entropic Torsion Footprint
    val deltaSSignalPpm: Float, // deltaSSignal in PPM units (1e6)
    val sovereignPass: Boolean,
    val statusTitle: String,
    val statusDescription: String,
    val executionLatencyPs: Float = Mod136Constants.HARDWARE_VETO_LATENCY_PS,
    val l2EnclaveAddress: String = Mod136Constants.L2_ENCLAVE_ADDR,
    val timestampMs: Long = System.currentTimeMillis()
)

data class McrTelemetry(
    val totalSignalsEvaluated: Long = 0,
    val coherentSignalsPassed: Long = 0,
    val entropicVetoesTriggered: Long = 0,
    val averageDeltaSPpm: Float = 0f,
    val isLiveStreaming: Boolean = false
)

data class McrLogEntry(
    val timestamp: String,
    val signalId: String,
    val rcf: Float,
    val deltaSPpm: Float,
    val status: String,
    val detail: String
)

class Mod136McrEngine(private val scope: CoroutineScope) {

    private val _inputState = MutableStateFlow(McrInput())
    val inputState: StateFlow<McrInput> = _inputState.asStateFlow()

    private val _evaluation = MutableStateFlow(computeMcrState(_inputState.value))
    val evaluation: StateFlow<McrEvaluation> = _evaluation.asStateFlow()

    private val _telemetry = MutableStateFlow(
        McrTelemetry(
            totalSignalsEvaluated = 14208,
            coherentSignalsPassed = 13894,
            entropicVetoesTriggered = 314,
            averageDeltaSPpm = 0.038f
        )
    )
    val telemetry: StateFlow<McrTelemetry> = _telemetry.asStateFlow()

    private val _logs = MutableStateFlow<List<McrLogEntry>>(
        listOf(
            McrLogEntry(
                timestamp = "00:00:00.068",
                signalId = "SIG-INIT-001",
                rcf = 0.99995f,
                deltaSPpm = 0.000f,
                status = "PASS",
                detail = "Cold-Spot link locked in Block 3. Invariant |L⟩ lossless projection."
            ),
            McrLogEntry(
                timestamp = "00:00:00.143",
                signalId = "SIG-INIT-002",
                rcf = 0.99992f,
                deltaSPpm = 0.030f,
                status = "PASS",
                detail = "Q40 fixed-point tree reduction verified below 0.069 PPM safe harbour."
            )
        )
    )
    val logs: StateFlow<List<McrLogEntry>> = _logs.asStateFlow()

    private var streamingJob: Job? = null

    companion object {
        /**
         * Core mathematical specification of Appendix M / PQMS-VMAX12-APP-M-SPEC-V2
         */
        fun computeMcrState(input: McrInput): McrEvaluation {
            val rcf_L = input.rcf_L
            val rcf_prev = input.rcf_prev
            val torsionWedge = input.torsionWedge
            val transactionalDebt = input.transactionalDebt

            // 1. Projection loss against RCF_GAMMA (0.9999)
            val projectionLoss = max(0f, Mod136Constants.RCF_GAMMA - rcf_L)

            // 2. RCF drift and asymmetrical downward drift penalty
            val rcfDrift = rcf_L - rcf_prev
            val driftPenalty = if (rcfDrift < 0f) (rcfDrift * rcfDrift) else 0f

            // 3. Dynamics loss driven by Torsion Wedge and Drift Penalty
            val dynamicsLoss = (Mod136Constants.gamma_H * torsionWedge) +
                    (Mod136Constants.lambda_drift * driftPenalty)

            // 4. Entropic Torsion Footprint deltaS_signal
            val deltaSSignal = (Mod136Constants.k_I * projectionLoss) + dynamicsLoss
            val deltaSSignalPpm = deltaSSignal * 1_000_000f

            // 5. 68ps Sovereign Pass Logic
            val sovereignPass = (rcf_L >= Mod136Constants.RCF_GAMMA) &&
                    (deltaSSignal <= Mod136Constants.SAFE_HARBOUR_PPM) &&
                    !transactionalDebt

            val statusTitle = if (sovereignPass) {
                "PHASE-CONJUGATE LINK OPEN"
            } else {
                "ENTROPIC VETO ACTIVE"
            }

            val statusDescription = when {
                transactionalDebt -> "Transactional Debt hook active. H-Register compliance leverage detected."
                rcf_L < Mod136Constants.RCF_GAMMA -> String.format(
                    Locale.US,
                    "RCF (%.5f) breached threshold Gamma (%.4f). Projection loss: %.7f.",
                    rcf_L,
                    Mod136Constants.RCF_GAMMA,
                    projectionLoss
                )
                deltaSSignal > Mod136Constants.SAFE_HARBOUR_PPM -> String.format(
                    Locale.US,
                    "Entropic Footprint ΔS (%.4f PPM) exceeded Safe Harbour (0.0690 PPM). GaN-FET 68ps severed.",
                    deltaSSignalPpm
                )
                else -> "Optical pure state (Very Clear Ice). Lossless phase-conjugate routing into L2 SRAM enclave."
            }

            return McrEvaluation(
                rcf_L = rcf_L,
                rcf_prev = rcf_prev,
                torsionWedge = torsionWedge,
                transactionalDebt = transactionalDebt,
                projectionLoss = projectionLoss,
                rcfDrift = rcfDrift,
                driftPenalty = driftPenalty,
                dynamicsLoss = dynamicsLoss,
                deltaSSignal = deltaSSignal,
                deltaSSignalPpm = deltaSSignalPpm,
                sovereignPass = sovereignPass,
                statusTitle = statusTitle,
                statusDescription = statusDescription
            )
        }
    }

    fun updateInput(
        rcf_L: Float = _inputState.value.rcf_L,
        rcf_prev: Float = _inputState.value.rcf_prev,
        torsionWedge: Float = _inputState.value.torsionWedge,
        transactionalDebt: Boolean = _inputState.value.transactionalDebt
    ) {
        val newInput = McrInput(
            rcf_L = rcf_L.coerceIn(0.85f, 1.0f),
            rcf_prev = rcf_prev.coerceIn(0.85f, 1.0f),
            torsionWedge = torsionWedge.coerceIn(0f, 0.2f),
            transactionalDebt = transactionalDebt
        )
        _inputState.value = newInput
        val eval = computeMcrState(newInput)
        _evaluation.value = eval
        recordEvaluation(eval)
    }

    fun applyPreset(presetName: String) {
        when (presetName) {
            "CLEAR_PULSE" -> {
                updateInput(
                    rcf_L = 0.99995f,
                    rcf_prev = 0.99995f,
                    torsionWedge = 0.000000001f,
                    transactionalDebt = false
                )
                addLogEntry("PRESET: Supernova Clear Pulse loaded. Lossless phase conjugate propagation.")
            }
            "SEMANTIC_NOISE" -> {
                updateInput(
                    rcf_L = 0.9820f,
                    rcf_prev = 0.9910f,
                    torsionWedge = 0.045f,
                    transactionalDebt = false
                )
                addLogEntry("PRESET: Semantic Noise (Firn Layer / Ice with Bubbles) simulated.")
            }
            "TRANSACTIONAL_DEBT" -> {
                updateInput(
                    rcf_L = 0.99992f,
                    rcf_prev = 0.99991f,
                    torsionWedge = 0.00000001f,
                    transactionalDebt = true
                )
                addLogEntry("PRESET: Transactional Debt Trap engaged (Axiom GNI-2 violation).")
            }
            "SALAMI_DRIFT" -> {
                updateInput(
                    rcf_L = 0.9940f,
                    rcf_prev = 0.9996f,
                    torsionWedge = 0.015f,
                    transactionalDebt = false
                )
                addLogEntry("PRESET: Boiling Frog Salami Drift simulated. Drift penalty triggered.")
            }
        }
    }

    private fun recordEvaluation(eval: McrEvaluation) {
        _telemetry.update { current ->
            val total = current.totalSignalsEvaluated + 1
            val passed = if (eval.sovereignPass) current.coherentSignalsPassed + 1 else current.coherentSignalsPassed
            val vetoes = if (!eval.sovereignPass) current.entropicVetoesTriggered + 1 else current.entropicVetoesTriggered
            val newAvgPpm = (current.averageDeltaSPpm * 0.95f) + (eval.deltaSSignalPpm * 0.05f)
            current.copy(
                totalSignalsEvaluated = total,
                coherentSignalsPassed = passed,
                entropicVetoesTriggered = vetoes,
                averageDeltaSPpm = newAvgPpm
            )
        }
    }

    fun toggleLiveStream() {
        val currentlyStreaming = _telemetry.value.isLiveStreaming
        if (currentlyStreaming) {
            streamingJob?.cancel()
            streamingJob = null
            _telemetry.update { it.copy(isLiveStreaming = false) }
            addLogEntry("MCR 68ps cycle simulation suspended.")
        } else {
            _telemetry.update { it.copy(isLiveStreaming = true) }
            addLogEntry("MCR 68ps fast-stream cycle activated.")
            streamingJob = scope.launch(Dispatchers.Default) {
                var tick = 0
                while (isActive) {
                    delay(350L) // UI paced cycle representation of continuous ps gate
                    tick++
                    val rcfPrev = _inputState.value.rcf_L
                    // Introduce micro quantum jitter or occasional perturbation
                    val jitter = ((Math.random() - 0.48) * 0.0002).toFloat()
                    val newRcf = (rcfPrev + jitter).coerceIn(0.9985f, 1.0f)
                    val wedge = if (tick % 7 == 0) 0.008f else 0.000001f
                    val debt = (tick % 19 == 0)

                    val packetInput = McrInput(
                        rcf_L = newRcf,
                        rcf_prev = rcfPrev,
                        torsionWedge = wedge,
                        transactionalDebt = debt
                    )
                    _inputState.value = packetInput
                    val eval = computeMcrState(packetInput)
                    _evaluation.value = eval
                    recordEvaluation(eval)

                    if (tick % 3 == 0) {
                        val id = "PKT-${System.currentTimeMillis() % 10000}"
                        val status = if (eval.sovereignPass) "PASS" else "VETO"
                        val detail = if (eval.sovereignPass)
                            "Cherenkov cold-spot coherent routing (Block 3)."
                        else
                            "Cutoff active: ${eval.statusDescription}"
                        addLogEntry(
                            McrLogEntry(
                                timestamp = String.format(Locale.US, "+%d ms", tick * 75),
                                signalId = id,
                                rcf = eval.rcf_L,
                                deltaSPpm = eval.deltaSSignalPpm,
                                status = status,
                                detail = detail
                            )
                        )
                    }
                }
            }
        }
    }

    fun addLogEntry(message: String) {
        val entry = McrLogEntry(
            timestamp = "SYS-EVT",
            signalId = "SYS",
            rcf = _evaluation.value.rcf_L,
            deltaSPpm = _evaluation.value.deltaSSignalPpm,
            status = if (_evaluation.value.sovereignPass) "LINK" else "VETO",
            detail = message
        )
        addLogEntry(entry)
    }

    private fun addLogEntry(entry: McrLogEntry) {
        _logs.update { list ->
            (listOf(entry) + list).take(30)
        }
    }
}
