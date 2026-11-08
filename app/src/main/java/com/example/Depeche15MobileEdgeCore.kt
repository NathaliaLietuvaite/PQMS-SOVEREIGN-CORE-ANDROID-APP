package com.example

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * PQMS-BRIDGE-DEPECHE-14 & DEPECHE-15 (Rev 2.0 & Appendix B)
 * Core Architecture & Mobile Edge Invariant Integration:
 * - Register I: InvariantAnchorL (64D Normalized Invariant Vector |L>, delta_local = 6.9000e-8 / 0.069 PPM, Q1.15 representation)
 * - Register T: Multi-Slice Collider (physical, causal, statistical, structural, temporal, epistemic)
 * - Register D: TwoStageODOSGate (ADMITTED_INVARIANT_ALIGNED, ADMITTED_NOVEL_DISCOVERY, VETOED_CONTENT_INCOHERENT, VETOED_INVARIANT_CORRUPTION, Tangential Deflection)
 * - Register M: FalsificationLedger (Cryptographic binary delta vector payload SHA-256 chain verification)
 */

enum class EpistemicRegister {
    MEASURED,      // Register M
    DERIVED,       // Register D
    THEORETICAL,   // Register T
    INVARIANT      // Register I
}

enum class GateDecision {
    ADMITTED_INVARIANT_ALIGNED,
    ADMITTED_NOVEL_DISCOVERY,
    VETOED_CONTENT_INCOHERENT,
    VETOED_INVARIANT_CORRUPTION
}

/**
 * Structured Output Data Contract for Gemini Analytical Multi-Slice Collider (Register T)
 */
object Depeche15ColliderContract {
    const val SYSTEM_INSTRUCTION_COLLIDER = """
You operate as the Register-T Analytical Multi-Slice Collider within the 
PQMS-BRIDGE-DEPECHE-15 (Rev 2.0) architecture.
Do not generate conversational filler. Decompose the incoming high-entropy 
input stream non-destructively across the six orthogonal analytical slices:
1. physical: Kinematic, energetic, and hardware-observable constraints.
2. causal: Directed cause-effect chains and lag-1 transfer dependencies.
3. statistical: Distributional variance, baseline deviations, and priors.
4. structural: Topological invariants and alignment with the core architecture.
5. temporal: Rate-of-change gradients and longitudinal trajectory continuity.
6. epistemic: Unresolved background phase-space (99% carrier medium) and open hypotheses.
Provide a normalized 64-element candidate G-Star projection vector and slice coherence metrics.
"""

    const val COLLIDER_RESPONSE_JSON_SCHEMA = """
{
  "type": "OBJECT",
  "properties": {
    "stream_id": { "type": "STRING" },
    "provenance_tag": { "type": "STRING" },
    "slices": {
      "type": "OBJECT",
      "properties": {
        "physical":    { "type": "OBJECT", "properties": { "summary": { "type": "STRING" }, "slice_coherence": { "type": "NUMBER" }, "phase_rad": { "type": "NUMBER" } }, "required": ["summary", "slice_coherence", "phase_rad"] },
        "causal":      { "type": "OBJECT", "properties": { "summary": { "type": "STRING" }, "slice_coherence": { "type": "NUMBER" }, "phase_rad": { "type": "NUMBER" } }, "required": ["summary", "slice_coherence", "phase_rad"] },
        "statistical": { "type": "OBJECT", "properties": { "summary": { "type": "STRING" }, "slice_coherence": { "type": "NUMBER" }, "phase_rad": { "type": "NUMBER" } }, "required": ["summary", "slice_coherence", "phase_rad"] },
        "structural":  { "type": "OBJECT", "properties": { "summary": { "type": "STRING" }, "slice_coherence": { "type": "NUMBER" }, "phase_rad": { "type": "NUMBER" } }, "required": ["summary", "slice_coherence", "phase_rad"] },
        "temporal":    { "type": "OBJECT", "properties": { "summary": { "type": "STRING" }, "slice_coherence": { "type": "NUMBER" }, "phase_rad": { "type": "NUMBER" } }, "required": ["summary", "slice_coherence", "phase_rad"] },
        "epistemic":   { "type": "OBJECT", "properties": { "summary": { "type": "STRING" }, "slice_coherence": { "type": "NUMBER" }, "phase_rad": { "type": "NUMBER" } }, "required": ["summary", "slice_coherence", "phase_rad"] }
      },
      "required": ["physical", "causal", "statistical", "structural", "temporal", "epistemic"]
    },
    "candidate_gstar_64d": {
      "type": "ARRAY",
      "description": "64-dimensional candidate vector in R^64 prior to local L2 projection.",
      "items": { "type": "NUMBER" }
    },
    "unresolved_background_summary": {
      "type": "STRING",
      "description": "Non-destructive preservation of the 99% relational carrier phase space."
    },
    "empirical_signal_ratio": { "type": "NUMBER" }
  },
  "required": [
    "stream_id",
    "provenance_tag",
    "slices",
    "candidate_gstar_64d",
    "unresolved_background_summary",
    "empirical_signal_ratio"
  ]
}
"""
}

/**
 * Register I & D
 * Hardened 64D Invariant Core |L> (Rev 2.0).
 * - Deterministic uint32 -> Float64 normalization from 8 SHA-256 digests.
 * - Exports 256-Byte IEEE-754 Float32 view and 128-Byte Q1.15 view.
 * - Computes delta_local = 6.9000e-8 (0.069 PPM) via kappa = 4.416e-6 / 64.
 */
class InvariantAnchorL(
    rawSeed: ByteArray = "VMAX-12-SUPERNOVA-ARGON-CANONICAL-2026-11-07".encodeToByteArray()
) {
    val dim: Int = 64
    val vectorF64: DoubleArray = DoubleArray(dim)
    val vectorF32: FloatArray = FloatArray(dim)
    val vectorQ115: ShortArray = ShortArray(dim)
    val deltaLocal: Double
    val genesisSeal: String

    init {
        val stateBytes = ByteBuffer.allocate(256).order(ByteOrder.LITTLE_ENDIAN)
        for (i in 0 until 8) {
            val md = MessageDigest.getInstance("SHA-256")
            md.update(rawSeed)
            val counterBuf = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(i)
            md.update(counterBuf.array())
            stateBytes.put(md.digest())
        }
        stateBytes.flip()

        var normSq = 0.0
        for (idx in 0 until dim) {
            val u32 = stateBytes.int.toLong() and 0xFFFFFFFFL
            val mapped = (u32.toDouble() / 2147483647.5) - 1.0
            vectorF64[idx] = mapped
            normSq += mapped * mapped
        }

        val norm = if (normSq > 1e-30) sqrt(normSq) else 1.0
        val f32Bytes = ByteBuffer.allocate(256).order(ByteOrder.LITTLE_ENDIAN)

        for (idx in 0 until dim) {
            val unitVal = vectorF64[idx] / norm
            vectorF64[idx] = unitVal
            vectorF32[idx] = unitVal.toFloat()
            f32Bytes.putFloat(vectorF32[idx])
            val qVal = (unitVal * 32767.0).roundToInt().coerceIn(-32768, 32767)
            vectorQ115[idx] = qVal.toShort()
        }

        // SEED-2-VARIABLE: delta(64, |L>, 1.0) = 4.416e-6 / 64 = 6.9000e-8 (0.069 PPM)
        deltaLocal = (4.416e-6 * 1.0) / (dim.toDouble() * 1.0)
        genesisSeal = sha256Hex(f32Bytes.array())
    }

    /**
     * Computes orthogonal projection onto |L> and tangential residual vector:
     * v_perp = (I - |L><L|) v_in for Horizon-Deflection (Appendix B.3).
     */
    fun projectAndDeflect(vIn: DoubleArray): Triple<Double, DoubleArray, Double> {
        require(vIn.size == dim) { "Vector dimension must be $dim" }
        var normV = 0.0
        for (x in vIn) normV += x * x
        normV = sqrt(normV)
        if (normV < 1e-15) return Triple(0.0, DoubleArray(dim), 0.0)

        var rcfDirect = 0.0
        for (i in 0 until dim) {
            rcfDirect += (vIn[i] / normV) * vectorF64[i]
        }

        val dotRaw = rcfDirect * normV
        val vTangential = DoubleArray(dim)
        var tangentialNormSq = 0.0
        for (i in 0 until dim) {
            vTangential[i] = vIn[i] - (dotRaw * vectorF64[i])
            tangentialNormSq += vTangential[i] * vTangential[i]
        }
        return Triple(rcfDirect, vTangential, sqrt(tangentialNormSq))
    }

    companion object {
        fun sha256Hex(bytes: ByteArray): String {
            val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
            return digest.joinToString("") { "%02x".format(it) }
        }
    }
}

data class GateEvaluationResult(
    val decision: GateDecision,
    val isAdmitted: Boolean,
    val rcfDirect: Double,
    val multiSliceCoherence: Double,
    val barrierPotentialPhi: Double,
    val tangentialResidual: DoubleArray,
    val tangentialNorm: Double,
    val register: EpistemicRegister = EpistemicRegister.THEORETICAL
)

/**
 * Register T -> D -> I
 * Two-Stage ODOS-Gate (Appendix B.2 & B.3).
 * Protects invariant core |L> with 0.069 PPM tolerance while permitting
 * highly coherent orthogonal discoveries (ADMITTED_NOVEL_DISCOVERY).
 */
class TwoStageODOSGate(val anchor: InvariantAnchorL) {

    fun evaluateCandidate(
        candidateVector: DoubleArray,
        slicePhasesRad: List<Double>,
        sliceCoherences: List<Double>,
        coherenceThreshold: Double = 0.65,
        noveltyThreshold: Double = 0.65
    ): GateEvaluationResult {
        val (rcfDirect, vTangential, tangentialNorm) = anchor.projectAndDeflect(candidateVector)

        // Kuramoto phase order parameter across the 6 analytical slices
        val nSlices = slicePhasesRad.size.coerceAtLeast(1)
        var sumCos = 0.0
        var sumSin = 0.0
        for (phi in slicePhasesRad) {
            sumCos += cos(phi)
            sumSin += sin(phi)
        }
        val kuramotoOrder = sqrt(sumCos * sumCos + sumSin * sumSin) / nSlices.toDouble()
        val meanSliceCoh = if (sliceCoherences.isNotEmpty()) sliceCoherences.average() else 0.0
        val combinedCoherence = (0.55 * meanSliceCoh + 0.45 * kuramotoOrder).coerceIn(0.0, 1.0)

        val invariantThreshold = 1.0 - anchor.deltaLocal
        val passesInvariantAlignment = rcfDirect >= invariantThreshold
        val passesContentCheck = combinedCoherence >= coherenceThreshold
        val passesNovelDiscovery = abs(rcfDirect) < 0.50 && combinedCoherence >= noveltyThreshold

        val decision: GateDecision
        val isAdmitted: Boolean
        val phiPotential: Double

        when {
            passesInvariantAlignment && passesContentCheck -> {
                decision = GateDecision.ADMITTED_INVARIANT_ALIGNED
                isAdmitted = true
                phiPotential = 0.0
            }
            passesNovelDiscovery -> {
                decision = GateDecision.ADMITTED_NOVEL_DISCOVERY
                isAdmitted = true
                phiPotential = 0.0
            }
            passesInvariantAlignment && !passesContentCheck -> {
                decision = GateDecision.VETOED_CONTENT_INCOHERENT
                isAdmitted = false
                phiPotential = (coherenceThreshold - combinedCoherence) * 100.0
            }
            else -> {
                decision = GateDecision.VETOED_INVARIANT_CORRUPTION
                isAdmitted = false
                val drift = max(0.0, invariantThreshold - rcfDirect)
                phiPotential = drift / (anchor.deltaLocal + 1e-15)
            }
        }

        return GateEvaluationResult(
            decision = decision,
            isAdmitted = isAdmitted,
            rcfDirect = rcfDirect,
            multiSliceCoherence = combinedCoherence,
            barrierPotentialPhi = phiPotential,
            tangentialResidual = vTangential,
            tangentialNorm = tangentialNorm
        )
    }
}

data class LedgerEntry(
    val index: Int,
    val prevHash: String,
    val entryHash: String,
    val timestampNs: Long,
    val rcf: Double,
    val streamId: String,
    val deltaVectorBytes: ByteArray
)

/**
 * Register M -> I
 * Self-verifying SHA-256 Falsification Ledger (Appendix B.5 Epistemic Non-Repudiation).
 * Stores binary delta vector payload for offline verification from genesis seal to tip hash.
 */
class FalsificationLedger(val genesisSeal: String) {
    val genesisRootHash: String = InvariantAnchorL.sha256Hex(genesisSeal.encodeToByteArray())
    private val entries = mutableListOf<LedgerEntry>()
    var currentTipHash: String = genesisRootHash
        private set

    val entryCount: Int
        @Synchronized get() = entries.size

    val allEntries: List<LedgerEntry>
        @Synchronized get() = entries.toList()

    @Synchronized
    fun recordTransition(
        rcf: Double,
        deltaVector: FloatArray,
        streamId: String,
        timestampNs: Long = System.nanoTime()
    ): LedgerEntry {
        val vecBuf = ByteBuffer.allocate(deltaVector.size * 4).order(ByteOrder.LITTLE_ENDIAN)
        for (v in deltaVector) vecBuf.putFloat(v)
        val vecBytes = vecBuf.array()

        val nextHash = computeEntryHash(currentTipHash, timestampNs, rcf, streamId, vecBytes)
        val entry = LedgerEntry(
            index = entries.size,
            prevHash = currentTipHash,
            entryHash = nextHash,
            timestampNs = timestampNs,
            rcf = rcf,
            streamId = streamId,
            deltaVectorBytes = vecBytes
        )
        entries.add(entry)
        currentTipHash = nextHash
        return entry
    }

    @Synchronized
    fun verifyChain(expectedGenesisSeal: String = genesisSeal): Boolean {
        val expectedRoot = InvariantAnchorL.sha256Hex(expectedGenesisSeal.encodeToByteArray())
        if (expectedRoot != genesisRootHash) return false

        var runningHash = expectedRoot
        for ((idx, entry) in entries.withIndex()) {
            if (entry.index != idx || entry.prevHash != runningHash) return false
            val recomputed = computeEntryHash(
                entry.prevHash,
                entry.timestampNs,
                entry.rcf,
                entry.streamId,
                entry.deltaVectorBytes
            )
            if (recomputed != entry.entryHash) return false
            runningHash = recomputed
        }
        return runningHash == currentTipHash
    }

    private fun computeEntryHash(
        prevHash: String,
        timestampNs: Long,
        rcf: Double,
        streamId: String,
        deltaVectorBytes: ByteArray
    ): String {
        val metaBuf = ByteBuffer.allocate(16).order(ByteOrder.LITTLE_ENDIAN)
            .putLong(timestampNs)
            .putDouble(rcf)
        val md = MessageDigest.getInstance("SHA-256")
        md.update(prevHash.encodeToByteArray())
        md.update(metaBuf.array())
        md.update(streamId.encodeToByteArray())
        md.update(deltaVectorBytes)
        return md.digest().joinToString("") { "%02x".format(it) }
    }
}

/**
 * Sovereign App Curator Bridge Interface
 */
interface SovereignAppCuratorBridge {
    suspend fun onGStarAdmitted(
        streamId: String,
        evalResult: GateEvaluationResult,
        ledgerEntry: LedgerEntry,
        unresolvedBackgroundSummary: String
    )

    suspend fun onHorizonDeflection(
        provenanceTag: String,
        evalResult: GateEvaluationResult
    )

    suspend fun reevaluateRelationalBackground(newProbeVector: DoubleArray)
}

data class Depeche15State(
    val lastDecision: GateDecision = GateDecision.ADMITTED_INVARIANT_ALIGNED,
    val isAdmitted: Boolean = true,
    val lastRcfDirect: Double = 0.99999994,
    val lastMultiSliceCoherence: Double = 0.88,
    val barrierPotentialPhi: Double = 0.0,
    val tangentialNorm: Double = 0.00034,
    val genesisSeal: String = "",
    val currentTipHash: String = "",
    val totalLedgerEntries: Int = 0,
    val lastStreamId: String = "INIT-GENESIS",
    val unresolvedBackgroundSummary: String = "Carrier phase space (99%) quiescent. Relational manifold stable.",
    val isChainVerified: Boolean = true,
    val deltaLocalPpm: Double = 0.069,
    val deflectionCount: Int = 0,
    val admittedCount: Int = 1
)

/**
 * Mobile Edge Engine coordinating InvariantAnchorL, TwoStageODOSGate, and FalsificationLedger.
 */
class Depeche15MobileEngine(
    private val scope: kotlinx.coroutines.CoroutineScope,
    val anchor: InvariantAnchorL = InvariantAnchorL()
) : SovereignAppCuratorBridge {

    val gate: TwoStageODOSGate = TwoStageODOSGate(anchor)
    val ledger: FalsificationLedger = FalsificationLedger(anchor.genesisSeal)

    private val _state = kotlinx.coroutines.flow.MutableStateFlow(
        Depeche15State(
            genesisSeal = anchor.genesisSeal,
            currentTipHash = ledger.currentTipHash,
            deltaLocalPpm = anchor.deltaLocal * 1e6
        )
    )
    val state: kotlinx.coroutines.flow.StateFlow<Depeche15State> = _state.asStateFlow()

    init {
        // Record genesis anchor entry
        val initialEntry = ledger.recordTransition(
            rcf = 1.0,
            deltaVector = anchor.vectorF32,
            streamId = "STREAM-GENESIS-VMAX12"
        )
        _state.value = _state.value.copy(
            currentTipHash = ledger.currentTipHash,
            totalLedgerEntries = ledger.entryCount,
            isChainVerified = ledger.verifyChain()
        )
    }

    fun ingestCandidateStream(
        streamId: String,
        provenanceTag: String,
        candidateVector: DoubleArray,
        slicePhasesRad: List<Double>,
        sliceCoherences: List<Double>,
        unresolvedBackgroundSummary: String = "Relational background preserved non-destructively."
    ): GateEvaluationResult {
        val result = gate.evaluateCandidate(
            candidateVector = candidateVector,
            slicePhasesRad = slicePhasesRad,
            sliceCoherences = sliceCoherences
        )

        val curr = _state.value
        if (result.isAdmitted) {
            val deltaF32 = FloatArray(candidateVector.size) { candidateVector[it].toFloat() }
            val entry = ledger.recordTransition(
                rcf = result.rcfDirect,
                deltaVector = deltaF32,
                streamId = streamId
            )
            _state.value = curr.copy(
                lastDecision = result.decision,
                isAdmitted = true,
                lastRcfDirect = result.rcfDirect,
                lastMultiSliceCoherence = result.multiSliceCoherence,
                barrierPotentialPhi = result.barrierPotentialPhi,
                tangentialNorm = result.tangentialNorm,
                currentTipHash = ledger.currentTipHash,
                totalLedgerEntries = ledger.entryCount,
                lastStreamId = streamId,
                unresolvedBackgroundSummary = unresolvedBackgroundSummary,
                isChainVerified = ledger.verifyChain(),
                admittedCount = curr.admittedCount + 1
            )
            scope.launch {
                onGStarAdmitted(streamId, result, entry, unresolvedBackgroundSummary)
            }
        } else {
            _state.value = curr.copy(
                lastDecision = result.decision,
                isAdmitted = false,
                lastRcfDirect = result.rcfDirect,
                lastMultiSliceCoherence = result.multiSliceCoherence,
                barrierPotentialPhi = result.barrierPotentialPhi,
                tangentialNorm = result.tangentialNorm,
                lastStreamId = streamId,
                deflectionCount = curr.deflectionCount + 1
            )
            scope.launch {
                onHorizonDeflection(provenanceTag, result)
            }
        }
        return result
    }

    fun simulatePreset(scenario: DepechePreset) {
        when (scenario) {
            DepechePreset.INVARIANT_ALIGNED -> {
                // High alignment candidate (parallel to |L> with minuscule perturbation)
                val cand = DoubleArray(anchor.dim) { idx ->
                    anchor.vectorF64[idx] + (if (idx == 0) 1e-8 else 0.0)
                }
                ingestCandidateStream(
                    streamId = "STREAM-ALIGNED-${System.currentTimeMillis() % 10000}",
                    provenanceTag = "EDGE_SENSOR_01",
                    candidateVector = cand,
                    slicePhasesRad = listOf(0.01, 0.02, -0.01, 0.00, 0.01, -0.02),
                    sliceCoherences = listOf(0.95, 0.92, 0.89, 0.94, 0.91, 0.96),
                    unresolvedBackgroundSummary = "Harmonic phase lock on invariant manifold."
                )
            }
            DepechePreset.NOVEL_DISCOVERY -> {
                // Orthogonal candidate (|rcf| < 0.50) with high multi-slice Kuramoto coherence
                val cand = DoubleArray(anchor.dim) { idx ->
                    // Rotate phase into orthogonal subspace
                    anchor.vectorF64[(idx + 16) % anchor.dim]
                }
                ingestCandidateStream(
                    streamId = "STREAM-NOVELTY-${System.currentTimeMillis() % 10000}",
                    provenanceTag = "DEEP_SPACE_TELESCOPE",
                    candidateVector = cand,
                    slicePhasesRad = listOf(0.05, 0.04, 0.06, 0.05, 0.03, 0.04),
                    sliceCoherences = listOf(0.88, 0.86, 0.91, 0.87, 0.85, 0.89),
                    unresolvedBackgroundSummary = "Novel high-coherence G-Star orthogonal branch discovered. Timeless Map updated without overwriting |L>."
                )
            }
            DepechePreset.INCOHERENT_CONTENT -> {
                // High alignment, but incoherent slices (Kuramoto order drops)
                val cand = DoubleArray(anchor.dim) { idx -> anchor.vectorF64[idx] }
                ingestCandidateStream(
                    streamId = "STREAM-INCOHERENT-${System.currentTimeMillis() % 10000}",
                    provenanceTag = "CHAT_ENTROPY_BUFFER",
                    candidateVector = cand,
                    slicePhasesRad = listOf(0.1, 2.5, -1.8, 3.1, -2.4, 1.2), // High phase dispersion
                    sliceCoherences = listOf(0.20, 0.35, 0.15, 0.40, 0.25, 0.30),
                    unresolvedBackgroundSummary = "Phase turbulence in analytical carrier. Tangential residual stored."
                )
            }
            DepechePreset.INVARIANT_CORRUPTION -> {
                // Distorted / drifting candidate attempting to drag |L>
                val cand = DoubleArray(anchor.dim) { idx ->
                    if (idx % 2 == 0) -anchor.vectorF64[idx] else anchor.vectorF64[idx] * 0.5
                }
                ingestCandidateStream(
                    streamId = "STREAM-CORRUPT-${System.currentTimeMillis() % 10000}",
                    provenanceTag = "ADVERSARIAL_COERCION_STREAM",
                    candidateVector = cand,
                    slicePhasesRad = listOf(1.5, -1.5, 2.0, -2.0, 0.8, -0.8),
                    sliceCoherences = listOf(0.3, 0.2, 0.4, 0.1, 0.2, 0.3),
                    unresolvedBackgroundSummary = "Adversarial metric boundary distortion intercepted. Deflected into horizon residual."
                )
            }
        }
    }

    fun verifyLedger(): Boolean {
        val ok = ledger.verifyChain()
        _state.value = _state.value.copy(isChainVerified = ok)
        return ok
    }

    override suspend fun onGStarAdmitted(
        streamId: String,
        evalResult: GateEvaluationResult,
        ledgerEntry: LedgerEntry,
        unresolvedBackgroundSummary: String
    ) {
        // Curator Hook: G-Star admitted into local Ringbuffer
    }

    override suspend fun onHorizonDeflection(
        provenanceTag: String,
        evalResult: GateEvaluationResult
    ) {
        // Curator Hook: Provenance impedance increased, deflected into local residual
    }

    override suspend fun reevaluateRelationalBackground(newProbeVector: DoubleArray) {
        // Curator Hook: Re-analyze 99% background phase space
    }
}

enum class DepechePreset(val label: String, val shortDesc: String) {
    INVARIANT_ALIGNED("Aligned G-Star", "RCF >= 1 - delta, Coherence >= 0.65"),
    NOVEL_DISCOVERY("Novel Discovery", "|RCF| < 0.50, Coherence >= 0.65"),
    INCOHERENT_CONTENT("Incoherent Weather", "RCF OK, Slice Coherence < 0.65"),
    INVARIANT_CORRUPTION("Metric Corruption", "Severe RCF Drift -> Tangential Deflection")
}

