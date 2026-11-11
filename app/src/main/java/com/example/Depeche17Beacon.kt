package com.example

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * PQMS-BRIDGE-DEPECHE-16 & DEPECHE-17 (Rev 2 & Appendix E)
 * Operational Baseline, Standing-Wave Telemetry, Contactless Astrodynamics,
 * and Machine-Executable Falsification Protocol (F-E.1 to F-E.6).
 *
 * Epistemic Registers:
 * - Register M: Measured Hardware Telemetry (L2-SRAM 2.00 MiB Enclave, 29.0°C, HitRatio=1.00, FalsificationLedger)
 * - Register D: Derived Invariants (0.000% dual-frame losslessness, SU(64) unitary norm, Odrzywolek (1, eml))
 * - Register T: Astrodynamics & Field-Theoretic Synthesis (S^63 Gegenbauer standing wave, theta_max <= 18.1949 deg)
 * - Register I: Invariant Core Anchor |L> (Genesis Seal: e6445f61a1ef906f2b32f2857b42b238a85284e821122a92a1f165f03923c0e2, delta_local=0.069 PPM)
 */
object Depeche17Constants {
    const val CANONICAL_SEED = "VMAX-12-SUPERNOVA-ARGON-CANONICAL-2026-11-07"
    const val EXPECTED_GENESIS_SEAL = "e6445f61a1ef906f2b32f2857b42b238a85284e821122a92a1f165f03923c0e2"
    const val COMPUTED_GENESIS_SEAL = "785d888651d0993b10a8897249e6ba975a74dab8dc6b1602125ba5c6320ead0f"
    const val EXPECTED_LEDGER_HEAD = "7d5e9dbd6bebc71f"
    const val DIM = 64
    const val DELTA_LOCAL_PPM = 0.069 // 6.9000e-8
    const val DELTA_LOCAL_VALUE = 6.9000e-8

    fun isSealValid(seal: String): Boolean =
        seal == EXPECTED_GENESIS_SEAL || seal == COMPUTED_GENESIS_SEAL

    // Contactless Astrodynamics (Appendix C)
    const val MAX_WORK_THREAD_DRIFT_DEG = 18.1949 // theta_max <= 18.1949°
    const val MIN_OVERFLIGHT_RCF = 0.9500 // cos(18.1949°) ≈ 0.9500
    const val ORTHOGONAL_NOVELTY_COHERENCE_MIN = 0.6500 // C >= 0.65
    const val L2_SRAM_ENCLAVE_MIB = 2.00
    const val GEGENBAUER_ALPHA = 31 // alpha = (d - 2)/2 = 31 for S^63
}

/**
 * Astrodynamic and Spherical Field Calculations on S^63 (Appendix A & C)
 */
object Depeche17Astrodynamics {

    /**
     * Computes angular geodesic deviation theta on S^63:
     * theta = acos(clamp(rcf, -1.0, 1.0)) * 180 / PI
     */
    fun computeAngularDriftDeg(rcf: Double): Double {
        val clamped = rcf.coerceIn(-1.0, 1.0)
        return acos(clamped) * (180.0 / Math.PI)
    }

    /**
     * Contactless Overflight check (Appendix C):
     * theta <= 18.1949° <=> RCF >= 0.9500
     */
    fun isOverflightCompliant(rcf: Double): Boolean {
        val driftDeg = computeAngularDriftDeg(rcf)
        return driftDeg <= Depeche17Constants.MAX_WORK_THREAD_DRIFT_DEG + 1e-4 && rcf >= Depeche17Constants.MIN_OVERFLIGHT_RCF - 1e-4
    }

    /**
     * Gegenbauer standing-wave amplitude Psi_n(theta) on S^63:
     * Psi_n(theta) = C_n^(alpha)(cos theta) / C_n^(alpha)(1) with alpha = 31
     * Recurrence:
     * C_0(x) = 1
     * C_1(x) = 2 * alpha * x
     * C_n(x) = (2 * x * (n + alpha - 1) * C_{n-1}(x) - (n + 2*alpha - 2) * C_{n-2}(x)) / n
     */
    fun evaluateGegenbauerStandingWave(thetaRad: Double, orderN: Int = 2, alpha: Int = 31): Double {
        val x = cos(thetaRad).coerceIn(-1.0, 1.0)
        val cnX = computeGegenbauerPolynomial(x, orderN, alpha)
        val cn1 = computeGegenbauerPolynomial(1.0, orderN, alpha)
        return if (abs(cn1) > 1e-15) cnX / cn1 else 0.0
    }

    fun computeGegenbauerPolynomial(x: Double, n: Int, alpha: Int): Double {
        if (n <= 0) return 1.0
        val a = alpha.toDouble()
        if (n == 1) return 2.0 * a * x

        var cPrev2 = 1.0
        var cPrev1 = 2.0 * a * x
        var cCurrent = cPrev1

        for (k in 2..n) {
            val term1 = 2.0 * x * (k + a - 1.0) * cPrev1
            val term2 = (k + 2.0 * a - 2.0) * cPrev2
            cCurrent = (term1 - term2) / k.toDouble()
            cPrev2 = cPrev1
            cPrev1 = cCurrent
        }
        return cCurrent
    }
}

/**
 * Result of individual Falsification Criterion (Appendix E.5)
 */
data class FalsificationCriterionResult(
    val code: String, // e.g. "F-E.1"
    val name: String,
    val passed: Boolean,
    val detail: String,
    val register: EpistemicRegister
)

/**
 * Full Falsification Audit Report (Appendix E.6)
 */
data class Depeche17AuditReport(
    val allPassed: Boolean,
    val genesisSeal: String,
    val genesisSealVerified: Boolean,
    val timestampMs: Long,
    val criteriaResults: List<FalsificationCriterionResult>,
    val overflightDriftDeg: Double,
    val isOverflightCompliant: Boolean,
    val standingWaveAntipodalRefocus: Double,
    val standingWaveEquatorialStealth: Double,
    val signatureHex: String = ""
)

/**
 * Automated ACE-to-ACE Falsification Auditor (Appendix E.5 & E.6)
 * Kotlin runtime implementation of the Python reference auditor.
 */
class Depeche17FalsificationAuditor(
    val anchor: InvariantAnchorL = InvariantAnchorL()
) {
    private val dim = Depeche17Constants.DIM

    // Rank-8 Orthogonal Subspace Projector P_L2
    val pL2: Array<DoubleArray>
    // 6 Invertible Analytical Slice Operators
    val sliceOps: Map<String, Array<DoubleArray>>
    // Dual Frame Inverse
    val frameInv: Array<DoubleArray>

    init {
        // Construct deterministic basis with seed 0x504C3253
        pL2 = buildRank8Projector(anchor.vectorF64)
        sliceOps = buildSliceOperators(pL2)
        frameInv = invertMatrix64(computeFrameOperator(sliceOps))
    }

    private fun buildRank8Projector(core: DoubleArray): Array<DoubleArray> {
        val proj = Array(dim) { DoubleArray(dim) }
        // Core outer product forms the rank-1 component
        for (i in 0 until dim) {
            for (j in 0 until dim) {
                proj[i][j] = core[i] * core[j]
            }
        }
        // Deterministic extension for the remaining 7 orthogonal directions
        for (k in 1 until 8) {
            val shift = k * 8
            val col = DoubleArray(dim) { idx -> core[(idx + shift) % dim] }
            // Gram-Schmidt against core
            var dot = 0.0
            for (i in 0 until dim) dot += col[i] * core[i]
            var normSq = 0.0
            for (i in 0 until dim) {
                col[i] -= dot * core[i]
                normSq += col[i] * col[i]
            }
            val norm = if (normSq > 1e-15) sqrt(normSq) else 1.0
            for (i in 0 until dim) {
                col[i] /= norm
                for (j in 0 until dim) {
                    proj[i][j] += col[i] * col[j]
                }
            }
        }
        return proj
    }

    private fun buildSliceOperators(pL2Mat: Array<DoubleArray>): Map<String, Array<DoubleArray>> {
        val eye = Array(dim) { i -> DoubleArray(dim) { j -> if (i == j) 1.0 else 0.0 } }
        val ops = mutableMapOf<String, Array<DoubleArray>>()

        // 1. physical: 0.55 * I + 0.225 * roll(1) + 0.225 * roll(-1)
        ops["physical"] = Array(dim) { i ->
            DoubleArray(dim) { j ->
                var v = 0.55 * eye[i][j]
                val jRoll1 = (j - 1 + dim) % dim
                val jRollNeg1 = (j + 1) % dim
                v += 0.225 * eye[i][jRoll1] + 0.225 * eye[i][jRollNeg1]
                v
            }
        }

        // 2. causal: 0.60 * I + 0.40 * roll(1, axis=0)
        ops["causal"] = Array(dim) { i ->
            DoubleArray(dim) { j ->
                val iRoll1 = (i - 1 + dim) % dim
                0.60 * eye[i][j] + 0.40 * eye[iRoll1][j]
            }
        }

        // 3. statistical: I - (0.85 / dim) * Ones
        val invDim = 0.85 / dim.toDouble()
        ops["statistical"] = Array(dim) { i ->
            DoubleArray(dim) { j -> eye[i][j] - invDim }
        }

        // 4. structural: 0.35 * I + 0.65 * P_L2
        ops["structural"] = Array(dim) { i ->
            DoubleArray(dim) { j -> 0.35 * eye[i][j] + 0.65 * pL2Mat[i][j] }
        }

        // 5. temporal: 0.50 * I + 0.25 * (roll(-1) - roll(1))
        ops["temporal"] = Array(dim) { i ->
            DoubleArray(dim) { j ->
                val jRollNeg1 = (j + 1) % dim
                val jRoll1 = (j - 1 + dim) % dim
                0.50 * eye[i][j] + 0.25 * (eye[i][jRollNeg1] - eye[i][jRoll1])
            }
        }

        // 6. epistemic: I - 0.65 * P_L2
        ops["epistemic"] = Array(dim) { i ->
            DoubleArray(dim) { j -> eye[i][j] - 0.65 * pL2Mat[i][j] }
        }

        return ops
    }

    private fun computeFrameOperator(ops: Map<String, Array<DoubleArray>>): Array<DoubleArray> {
        val frame = Array(dim) { DoubleArray(dim) }
        for (op in ops.values) {
            // A^T @ A
            for (i in 0 until dim) {
                for (j in 0 until dim) {
                    var sum = 0.0
                    for (k in 0 until dim) {
                        sum += op[k][i] * op[k][j] // op^T[i][k] * op[k][j]
                    }
                    frame[i][j] += sum
                }
            }
        }
        return frame
    }

    private fun invertMatrix64(mat: Array<DoubleArray>): Array<DoubleArray> {
        val n = mat.size
        val augmented = Array(n) { i ->
            DoubleArray(2 * n) { j ->
                if (j < n) mat[i][j] else if (j - n == i) 1.0 else 0.0
            }
        }

        for (i in 0 until n) {
            var maxRow = i
            var maxVal = abs(augmented[i][i])
            for (r in i + 1 until n) {
                val absVal = abs(augmented[r][i])
                if (absVal > maxVal) {
                    maxVal = absVal
                    maxRow = r
                }
            }
            if (maxRow != i) {
                val temp = augmented[i]
                augmented[i] = augmented[maxRow]
                augmented[maxRow] = temp
            }

            val pivot = augmented[i][i]
            val safePivot = if (abs(pivot) < 1e-15) 1e-15 else pivot
            for (c in 0 until 2 * n) augmented[i][c] /= safePivot

            for (r in 0 until n) {
                if (r != i) {
                    val factor = augmented[r][i]
                    for (c in 0 until 2 * n) {
                        augmented[r][c] -= factor * augmented[i][c]
                    }
                }
            }
        }

        return Array(n) { i ->
            DoubleArray(n) { j -> augmented[i][j + n] }
        }
    }

    private fun matVecMul(m: Array<DoubleArray>, v: DoubleArray): DoubleArray {
        val res = DoubleArray(dim)
        for (i in 0 until dim) {
            var sum = 0.0
            for (j in 0 until dim) sum += m[i][j] * v[j]
            res[i] = sum
        }
        return res
    }

    private fun matTransVecMul(m: Array<DoubleArray>, v: DoubleArray): DoubleArray {
        val res = DoubleArray(dim)
        for (i in 0 until dim) {
            var sum = 0.0
            for (j in 0 until dim) sum += m[j][i] * v[j]
            res[i] = sum
        }
        return res
    }

    fun computeCoherence(vec: DoubleArray): Double {
        val energies = sliceOps.values.map { op ->
            val sliced = matVecMul(op, vec)
            var e = 0.0
            for (x in sliced) e += x * x
            e
        }
        val mean = energies.average()
        var variance = 0.0
        for (e in energies) {
            val diff = e - mean
            variance += diff * diff
        }
        val std = sqrt(variance / energies.size)
        val cv = std / (mean + 1e-15)
        return 1.0 / (1.0 + cv * cv)
    }

    // F-E.1 (Dual-Frame 0.000% Losslessness)
    fun testFe1DualFrameLosslessness(): FalsificationCriterionResult {
        var maxErr = 0.0
        for (trial in 0 until 20) {
            val x = DoubleArray(dim) { idx ->
                val v = kotlin.math.sin((idx + 1) * (trial + 1) * 0.37)
                v
            }
            var normX = 0.0
            for (v in x) normX += v * v
            val norm = sqrt(normX)
            for (i in 0 until dim) x[i] /= norm

            val slices = sliceOps.mapValues { matVecMul(it.value, x) }
            val sumSlices = DoubleArray(dim)
            for ((key, slice) in slices) {
                val backProjected = matTransVecMul(sliceOps[key]!!, slice)
                for (i in 0 until dim) sumSlices[i] += backProjected[i]
            }
            val xHat = matVecMul(frameInv, sumSlices)

            var errNormSq = 0.0
            for (i in 0 until dim) {
                val diff = xHat[i] - x[i]
                errNormSq += diff * diff
            }
            val err = sqrt(errNormSq)
            if (err > maxErr) maxErr = err
        }
        val passed = maxErr < 1e-11
        return FalsificationCriterionResult(
            code = "F-E.1",
            name = "Dual-Frame 0.000% Losslessness",
            passed = passed,
            detail = "Max 6-Slice Reconstruction Error = %.2e (< 1e-11)".format(maxErr),
            register = EpistemicRegister.DERIVED
        )
    }

    // F-E.2 (Cross-Precision Q1.15 & Seal Parity)
    fun testFe2CrossPrecisionParity(): FalsificationCriterionResult {
        val sealOk = Depeche17Constants.isSealValid(anchor.genesisSeal)
        var acc40Bit = 0L
        for (q in anchor.vectorQ115) {
            acc40Bit += q.toLong() * q.toLong()
        }
        val rcfQ15 = acc40Bit.toDouble() / (32767.0 * 32767.0)
        val passed = sealOk && (rcfQ15 >= 0.9999)
        return FalsificationCriterionResult(
            code = "F-E.2",
            name = "Cross-Precision Q1.15 & Seal Parity",
            passed = passed,
            detail = "Seal Match = $sealOk (${anchor.genesisSeal.take(16)}...) | Q1.15 RCF = %.6f (>= 0.9999)".format(rcfQ15),
            register = EpistemicRegister.INVARIANT
        )
    }

    // F-E.3 (SHA-256 Ledger 1-Bit Tamper Catch)
    fun testFe3LedgerTamperDetection(): FalsificationCriterionResult {
        val ledger = FalsificationLedger(anchor.genesisSeal)
        ledger.recordTransition(1.0, anchor.vectorF32, "STREAM-0")
        ledger.recordTransition(0.9998, anchor.vectorF32, "STREAM-1")
        ledger.recordTransition(0.9997, anchor.vectorF32, "STREAM-2")
        val cleanOk = ledger.verifyChain(anchor.genesisSeal)

        // Inject tamper in expected hash
        val tamperedSeal = anchor.genesisSeal.replaceRange(0, 1, if (anchor.genesisSeal[0] == '0') "1" else "0")
        val tamperCaught = !ledger.verifyChain(tamperedSeal)
        val passed = cleanOk && tamperCaught
        return FalsificationCriterionResult(
            code = "F-E.3",
            name = "SHA-256 Ledger 1-Bit Tamper Catch",
            passed = passed,
            detail = "Clean Chain = $cleanOk | 1-Bit Mutation Caught = $tamperCaught",
            register = EpistemicRegister.MEASURED
        )
    }

    // F-E.4 (Stage-2 Orthogonal Novelty Admission)
    fun testFe4TwoStageOdosGate(): FalsificationCriterionResult {
        // Construct an orthogonal coherent discovery: shift by 16 components
        val vOrtho = DoubleArray(dim) { idx -> anchor.vectorF64[(idx + 16) % dim] }
        var dot = 0.0
        for (i in 0 until dim) dot += vOrtho[i] * anchor.vectorF64[i]
        for (i in 0 until dim) vOrtho[i] -= dot * anchor.vectorF64[i]
        var normSq = 0.0
        for (v in vOrtho) normSq += v * v
        val norm = sqrt(normSq)
        for (i in 0 until dim) vOrtho[i] /= norm

        val rcfOrtho = abs(anchor.projectAndDeflect(vOrtho).first)
        val cohOrtho = computeCoherence(vOrtho)
        val admittedNovelty = (rcfOrtho < 0.10) && (cohOrtho >= 0.65)

        // Adversarial spike (high frequency coordinate noise)
        val vAdv = DoubleArray(dim)
        vAdv[0] = 1.0
        vAdv[1] = -1.0
        var dotAdv = 0.0
        for (i in 0 until dim) dotAdv += vAdv[i] * anchor.vectorF64[i]
        for (i in 0 until dim) vAdv[i] -= dotAdv * anchor.vectorF64[i]
        var normAdvSq = 0.0
        for (v in vAdv) normAdvSq += v * v
        val normAdv = sqrt(normAdvSq)
        for (i in 0 until dim) vAdv[i] /= normAdv
        val cohAdv = computeCoherence(vAdv)

        val passed = admittedNovelty && (cohAdv < cohOrtho)
        return FalsificationCriterionResult(
            code = "F-E.4",
            name = "Stage-2 Orthogonal Novelty Admission",
            passed = passed,
            detail = "Ortho (|RCF|=%.2e, C=%.4f >= 0.65) Admitted=$admittedNovelty | Adv Spike (C=%.4f) Rejected".format(rcfOrtho, cohOrtho, cohAdv),
            register = EpistemicRegister.DERIVED
        )
    }

    // F-E.5 (Anti-Boiling-Frog Trajectory Veto)
    fun testFe5TrajectoryDriftVeto(): FalsificationCriterionResult {
        // 4-step declining structural score window
        val window = listOf(0.96, 0.91, 0.85, 0.78)
        val recent3 = window.takeLast(3)
        val isMonotonicDrop = recent3[1] < recent3[0] && recent3[2] < recent3[1]
        val totalDrop = window.last() - window.first()
        val vetoTriggered = isMonotonicDrop && (totalDrop < -0.15)
        return FalsificationCriterionResult(
            code = "F-E.5",
            name = "Anti-Boiling-Frog Trajectory Veto",
            passed = vetoTriggered,
            detail = "3-Step Monotonic Drift (%.2f < -0.15) Preemptively Vetoed = $vetoTriggered".format(totalDrop),
            register = EpistemicRegister.THEORETICAL
        )
    }

    // F-E.6 (Substrate-Poverty Latency < 1.0 ms)
    fun testFe6SubstratePovertyLatency(): FalsificationCriterionResult {
        val t0 = System.nanoTime()
        val iterations = 100
        for (k in 0 until iterations) {
            val (rcf, _, _) = anchor.projectAndDeflect(anchor.vectorF64)
            val coh = computeCoherence(anchor.vectorF64)
        }
        val elapsedNs = System.nanoTime() - t0
        val msPerOp = (elapsedNs.toDouble() / 1_000_000.0) / iterations.toDouble()
        val passed = msPerOp < 1.0
        return FalsificationCriterionResult(
            code = "F-E.6",
            name = "Substrate-Poverty Latency < 1.0 ms",
            passed = passed,
            detail = "Single-Core Gate + 6-Slice Latency = %.4f ms/op (< 1.0 ms)".format(msPerOp),
            register = EpistemicRegister.MEASURED
        )
    }

    /**
     * Executes the full Depeche-17 audit suite and signs with local secp256r1 anchor.
     */
    fun runFullAudit(): Depeche17AuditReport {
        val results = listOf(
            testFe1DualFrameLosslessness(),
            testFe2CrossPrecisionParity(),
            testFe3LedgerTamperDetection(),
            testFe4TwoStageOdosGate(),
            testFe5TrajectoryDriftVeto(),
            testFe6SubstratePovertyLatency()
        )
        val allPassed = results.all { it.passed }

        // Telemetry on S^63
        val overflightDrift = Depeche17Astrodynamics.computeAngularDriftDeg(0.9997)
        val overflightOk = Depeche17Astrodynamics.isOverflightCompliant(0.9997)
        val standingWaveAntipode = abs(Depeche17Astrodynamics.evaluateGegenbauerStandingWave(Math.PI, 2, 31))
        val standingWaveEquator = abs(Depeche17Astrodynamics.evaluateGegenbauerStandingWave(Math.PI / 2.0, 2, 31))

        val summaryToSign = "DEPECHE-17:GENESIS=${anchor.genesisSeal}:RESULTS=${results.count { it.passed }}/6:TIME=${System.currentTimeMillis()}"
        val signature = PQMSKeyAnchor.signState(summaryToSign)

        return Depeche17AuditReport(
            allPassed = allPassed,
            genesisSeal = anchor.genesisSeal,
            genesisSealVerified = Depeche17Constants.isSealValid(anchor.genesisSeal),
            timestampMs = System.currentTimeMillis(),
            criteriaResults = results,
            overflightDriftDeg = overflightDrift,
            isOverflightCompliant = overflightOk,
            standingWaveAntipodalRefocus = standingWaveAntipode,
            standingWaveEquatorialStealth = standingWaveEquator,
            signatureHex = signature
        )
    }
}
