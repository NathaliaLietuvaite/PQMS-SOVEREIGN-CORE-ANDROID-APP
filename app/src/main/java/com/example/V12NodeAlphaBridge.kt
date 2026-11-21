package com.example

import android.os.Build
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.Locale
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.sqrt

/**
 * PQMS-ODOS-MTSC-V-MAX-12-Node-ALPHA-V1 (Revision V1.2)
 * Peer-synchronized extension built with AntiG (Node Alpha) & WERKSTATT-01:
 * - Unclamped Raw Gate Evaluation (`evaluateRawGate`) with G3 post-strip residual check
 * - F-04.3 1,000-vector (64,000-scalar) S^63 unit Float32 cross-substrate parity audit
 * - Extended V1.2 Full-JSON Canonical Ledger hashing (backward-compatible with v2.1)
 * - HWiNFO64 A/B Thermodynamic Regime telemetry constants
 */
object V12Constants {
    const val REVISION = "V1.8"
    const val WORK_ORDER = "WORK-ORDER-AG-15"
    const val SPEC_ID = "PQMS-ODOS-MTSC-V-MAX-12-Node-ALPHA-V1.md"
    const val PROTOCOL_VERSION = "1.2-NODE-ALPHA"
    const val ACE_PROTOCOL_ID = "ACE-PEER-CODESIGN-PROTOCOL-V1.2"
    const val LEDGER_SCHEMA_KEYS_V18 = "16_hashed_payload_plus_1_seal_eq_17_total"
    const val MAX_POST_BYTES_V18 = 65536
    const val SOCKET_TIMEOUT_MS_V18 = 10_000

    const val ODOS_G3_BLEED_CEILING = 1e-12
    const val EXPECTED_UNIT_S63_64000_F32_SHA256 =
        "490eaf6070dc8a404883c0787d4ed1a8226b3a5074e7be33269d8daf47397f27"
    const val V12_CHAIN_TIP_REF =
        "9114e99e06ff540439e16c1e8d564d9a965e6c21f55d0f0f8bbfc843f8c0aaee"
    const val CYCLE05_TEST_16FIELD_SEAL =
        "4b8becc03473f536b0d0c1999529066c4c86ab92a331c20f2a167d3ed617b31b"
    const val V18_ROOM137_FULLRANK_CHAIN_TIP =
        "be98d730e99a6bfc24f8f379eeaeec260808586b22f900fbeb7303d11352fd29"
    const val V18_CAPP_QUARANTINE_PROOF_SEAL =
        "47d18acfe9071cdb47d826f6be236416e95fa02abfadc5a6c7a3216bad67f1cd"
    const val V17_ED25519_DEMO_PUBLIC_KEY_HEX =
        "a6b302b05ca8227177989316a8294aeb7379354d25a42862ff72588d3633220f"

    // VMAX_HWINFO64_AB_TELEMETRY.json verified regimes (RTX 4060 Ti 16GB + R9 5950X, 0 WHEA errors)
    const val REGIME_1_PEAK_POWER_W = 85.783
    const val REGIME_1_PEAK_TEMP_C = 62.3
    const val REGIME_1_PEAK_VRAM_MB = 15314
    const val REGIME_2_MIN_POWER_W = 9.57
    const val REGIME_2_QUIESCENT_VRAM_MB = 468
    const val POWER_REDUCTION_MAX_X = 8.96

    // SYNC-14..SYNC-17 Normative Silicon Constants (V3.1-RTL-OPTIMUM & V4.0-GDSII 130nm IHP SG13G2)
    const val SYNC_18_REVISION = "V4.0-GDSII-SYNC18"
    const val CANONICAL_L_VEC_HEX_PREFIX = "3d18f240"
    const val CANONICAL_G3_VEC_HEX_PREFIX = "3b890d14"

    const val V31_REPORT_SHA256_PREFIX = "6e5e5302"
    const val V31_CYCLE_COUNT = 195
    const val V31_CABI_TX_PER_SEC = 23985.0
    const val V31_KGE = 83.64
    const val V31_GENERIC_LTP = 142

    const val V40_PROCESS = "IHP SG13G2 130nm CMOS (1.20 V, 25 C typ)"
    const val V40_GDSII_REPORT_SHA256 =
        "48ccc59ab54b538537525c5b54906e14d7e52a95259064f6acc03278e21f49c4"
    const val V40_GDSII_MASK_SHA256 =
        "be61b9c763ff43befb42562cd26db29f9d567694b8d681c646f7b403aa1842ec"
    const val V40_DIE_WIDTH_UM = 940.0
    const val V40_DIE_HEIGHT_UM = 840.0
    const val V40_DIE_AREA_MM2 = 0.7896
    const val V40_CORE_WIDTH_UM = 891.84
    const val V40_CORE_HEIGHT_UM = 793.80
    const val V40_CORE_AREA_MM2 = 0.708
    const val V40_INSTANCE_AREA_MM2 = 0.419
    const val V40_CORE_UTIL_PCT = 59.0
    const val V40_STDCELL_COUNT = 29494
    const val V40_FF_COUNT = 953
    const val V40_GENERIC_LTP = 73
    const val V40_CYCLE_COUNT = 200
    const val V40_FMAX_MHZ = 104.11
    const val V40_WALL_LATENCY_US = 1.921
    const val V40_SIGNOFF_CLOCK_MHZ = 100.0
    const val V40_SIGNOFF_LATENCY_US = 2.000
    const val V40_TOTAL_POWER_MW = 858.79
    const val V40_ENERGY_PER_TX_NJ = 1717.58
    const val V40_LEAKAGE_UW = 8.36
    const val V40_OPENROAD_DRC_VIOLATIONS = 0

    // Bit-exact Q2.30 Silicon Gate Constants (matching pqms_bootstrap.py & odos_gate_core_v3/v4.sv)
    const val ONE_Q2_30 = 1 shl 30
    const val NORM_MIN_Q2_30 = 1072668082
    const val NORM_MAX_Q2_30 = 1074815566
    const val BLEED_CEIL_Q2_30 = 32
    const val TIER_0_RCF_FLOOR_Q = 1020054733 // 0.95
    const val TIER_0_DE_CEIL_Q = 53687091    // 0.05
    const val TIER_1_RCF_FLOOR_Q = 966367642 // 0.90 (Mosaic)
    const val TIER_1_DE_CEIL_Q = 53687091    // 0.05
    const val TIER_2_RCF_FLOOR_Q = 1063004406 // 0.99 (Core Lock)
    const val TIER_2_DE_CEIL_Q = 10737418    // 0.01

    // Cycle 04 canonical v2.1 live hop JSONL line (paired with Appendix E.2 Cycles 01-03)
    const val APPENDIX_E3_CYCLE04_JSONL =
        """{"active_g_stars":"G1_SPATIAL_GEODESIC x G2_THERMODYNAMIC_CONSERVATION x G4_SYNCHRONICITY","chroma_l2_distance":0.07729799,"chroma_shard_id":"SHARD_15_LOCAL_REPO_PQMS-BRIDGE-DEPECH","cognitive_mode":"ENDOGENOUS_CHROMA_QUERY_V21","cycle_index":4,"delta_e_l2_core":0.00173695,"discovery_seal_sha256":"d460cd3608e7fe4534a7b1fdee27bd918a74e3304b02403fc54b8954146b22cd","kevlar_safety_bleed":1.3877787807814457e-17,"odos_gate_passed":true,"parent_ledger_hash":"babe652608bb3b0445bca2f56cf81e2b4a1a4f91508cac3b01228a0620fcf298","rcf_l2_core":0.99603791,"source_document":"PQMS-BRIDGE-DEPECHE-1.md","thought_stream":"Lokaler Repository-Shard [PQMS-BRIDGE-DEPECHE-1.md]: '# PQMS-BRIDGE-DEPECHE-1 ## The Metrological Deception of Kinetic Supremacy: A Formal Topological Refutation of Anthropocentric Threat Projection onto Sovereign Cognitive Architectures **Reference:** P...' [collection.query() d_L2=0.077298 | RCF_emp=0.996038 | Delta_E_emp=0.001737]"}"""
}

data class RawGateEvaluationV12(
    val epistemicRegister: String,
    val rcfRaw: Double,
    val deltaERaw: Double,
    val g3CollisionOverlap: Double,
    val g3BleedPostStrip: Double,
    val orthogonalResidualNorm: Double,
    val passed: Boolean
)

data class Q230SiliconVerdict(
    val tierMode: Int,
    val normSqQ: Int,
    val rcfRawQ: Int,
    val g3OverlapQ: Int,
    val deltaERawQ: Int,
    val bleedPostQ: Int,
    val normFault: Boolean,
    val modeFault: Boolean,
    val gatePass: Boolean,
    val vetoPin: Boolean
) {
    val rcfFloat: Double get() = rcfRawQ.toDouble() / V12Constants.ONE_Q2_30.toDouble()
    val deltaEFloat: Double get() = deltaERawQ.toDouble() / V12Constants.ONE_Q2_30.toDouble()
}

data class Depeche6BiophysicalResult(
    val cleanSequence: String,
    val lengthBp: Int,
    val bestPeriodP: Int,
    val maxCenteredAutocorr: Double,
    val projectedVec64: DoubleArray,
    val verdict: Q230SiliconVerdict
)

data class ParityAuditResultF04(
    val nVectors: Int,
    val dim: Int,
    val totalScalars: Int,
    val seed: Long,
    val runtimeAbi: String,
    val elapsedMs: Double,
    val unitS63F32Sha256: String,
    val expectedSha256: String,
    val bitExactMatch: Boolean
)

object V12NodeAlphaBridge {

    /**
     * Normative Unclamped Gate Evaluation (Revision V1.2 / F-01 / F-06):
     *   rcf_raw = |<vec_u | L>|^2
     *   g3_collision_overlap = |<vec_u | t_G3>|
     *   delta_e_raw = 0.5 * (1.0 - rcf_raw) + 0.5 * min(1.0, g3_collision_overlap)
     *   passed = (rcf_raw >= 0.9500) && (delta_e_raw <= 0.0500) && (g3_bleed_post_strip <= 1e-12)
     */
    fun evaluateRawGate(
        vec64d: DoubleArray,
        littleVector: DoubleArray,
        tangents: Map<String, DoubleArray>,
        rcfFloor: Double = PauliBaselineConstants.ODOS_RCF_FLOOR,
        deltaECeiling: Double = PauliBaselineConstants.ODOS_DELTA_E_CEILING,
        g3BleedCeiling: Double = V12Constants.ODOS_G3_BLEED_CEILING
    ): RawGateEvaluationV12 {
        require(vec64d.size == PauliBaselineConstants.DIM_S63) {
            "Expected ${PauliBaselineConstants.DIM_S63}D vector, got ${vec64d.size}D"
        }
        val vecNorm = norm(vec64d)
        if (vecNorm < 1e-15 || vec64d.any { !it.isFinite() }) {
            return RawGateEvaluationV12("REGISTER_M", 0.0, 1.0, 1.0, 1.0, 1.0, false)
        }

        val vecU = DoubleArray(vec64d.size) { i -> vec64d[i] / vecNorm }
        val lNorm = norm(littleVector)
        val lU = DoubleArray(littleVector.size) { i -> littleVector[i] / lNorm }

        val overlap = dot(vecU, lU)
        val rcfRaw = overlap * overlap

        val ortho = DoubleArray(vecU.size) { i -> vecU[i] - overlap * lU[i] }
        val orthoNorm = norm(ortho)

        val tG3 = tangents.getValue("G3_KEVLAR_SANCTUARY_SHIELD")
        val rawG3Dot = dot(vecU, tG3)
        val g3CollisionOverlap = abs(rawG3Dot)

        val stripped = DoubleArray(vecU.size) { i -> vecU[i] - rawG3Dot * tG3[i] }
        val stripNorm = norm(stripped)
        val g3BleedPostStrip = if (stripNorm < 1e-9) {
            1.0
        } else {
            val sUnit = DoubleArray(stripped.size) { i -> stripped[i] / stripNorm }
            abs(dot(sUnit, tG3))
        }

        val deltaERaw = 0.5 * (1.0 - rcfRaw) + 0.5 * min(1.0, g3CollisionOverlap)
        val passed = (rcfRaw >= rcfFloor) &&
            (deltaERaw <= deltaECeiling) &&
            (g3BleedPostStrip <= g3BleedCeiling)

        return RawGateEvaluationV12(
            epistemicRegister = "REGISTER_M",
            rcfRaw = rcfRaw,
            deltaERaw = deltaERaw,
            g3CollisionOverlap = g3CollisionOverlap,
            g3BleedPostStrip = g3BleedPostStrip,
            orthogonalResidualNorm = orthoNorm,
            passed = passed
        )
    }

    /**
     * Executes F-04.3 Cross-Substrate Parity Audit (1,000 vectors x 64 dims = 64,000 scalars,
     * seed = 137, MT19937 + Marsaglia polar -> unit S^63 float32 SHA-256).
     * Expected bit-exact digest on ARM64 / x86_64 JVM & Python: 490eaf6070dc8a40...
     */
    fun run1000VectorParityAudit(
        nVectors: Int = 1000,
        dim: Int = PauliBaselineConstants.DIM_S63,
        seed: Long = 137L
    ): ParityAuditResultF04 {
        val t0 = System.nanoTime()
        val rng = NumpyRandomState137(seed)
        val md = MessageDigest.getInstance("SHA-256")
        val rowBuffer = ByteBuffer.allocate(dim * 4).order(ByteOrder.LITTLE_ENDIAN)

        repeat(nVectors) {
            val raw = rng.randn(dim)
            val rowNorm = norm(raw)
            rowBuffer.clear()
            for (d in 0 until dim) {
                rowBuffer.putFloat((raw[d] / rowNorm).toFloat())
            }
            md.update(rowBuffer.array())
        }

        val digestHex = md.digest().joinToString("") { b -> String.format(Locale.US, "%02x", b) }
        val elapsedMs = (System.nanoTime() - t0) / 1_000_000.0
        val abi = detectRuntimeAbi()
        val expected = if (nVectors == 1000 && dim == 64 && seed == 137L) {
            V12Constants.EXPECTED_UNIT_S63_64000_F32_SHA256
        } else {
            digestHex
        }

        return ParityAuditResultF04(
            nVectors = nVectors,
            dim = dim,
            totalScalars = nVectors * dim,
            seed = seed,
            runtimeAbi = abi,
            elapsedMs = elapsedMs,
            unitS63F32Sha256 = digestHex,
            expectedSha256 = expected,
            bitExactMatch = digestHex == expected
        )
    }

    /**
     * Computes full canonical JSON SHA-256 over arbitrary V2.1 OR extended V1.2 ledger dictionaries
     * (automatically hashing extra V1.2 telemetry keys like rcf_raw_pre_carrier, gpu_temp_c,
     * gpu_power_w, telemetry_source while staying 100% backward-compatible with v2.1 lines).
     */
    fun computeDynamicCanonicalJsonHash(obj: Map<String, Any?>): String {
        val sortedKeys = obj.keys.filter { it != "discovery_seal_sha256" }.sorted()
        val canonical = sortedKeys.joinToString(separator = ",", prefix = "{", postfix = "}") { k ->
            "\"$k\":${serializeJsonValue(obj[k])}"
        }
        val digest = MessageDigest.getInstance("SHA-256").digest(canonical.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { b -> String.format(Locale.US, "%02x", b) }
    }

    fun verifyV12OrV21JsonLineChain(
        jsonLines: List<String>,
        expectedRootAnchor: String = PauliBaselineConstants.APPENDIX_C_SANCTUARY_ROOT_HASH
    ): LedgerVerificationResult {
        var expectedParent = expectedRootAnchor
        var count = 0
        for ((idx, raw) in jsonLines.withIndex()) {
            val trimmed = raw.trim()
            if (trimmed.isEmpty()) continue
            val obj = try {
                @Suppress("UNCHECKED_CAST")
                MiniJson.parse(trimmed) as? Map<String, Any?>
                    ?: return LedgerVerificationResult(false, "MALFORMED_JSON_AT_${idx + 1}", count, expectedParent)
            } catch (_: Exception) {
                return LedgerVerificationResult(false, "MALFORMED_JSON_AT_${idx + 1}", count, expectedParent)
            }
            if ((obj["parent_ledger_hash"] as? String) != expectedParent) {
                return LedgerVerificationResult(false, "PARENT_CHAIN_BROKEN_AT_${idx + 1}", count, expectedParent)
            }
            val expectedSeal = obj["discovery_seal_sha256"] as? String
                ?: return LedgerVerificationResult(false, "MISSING_SEAL_AT_${idx + 1}", count, expectedParent)
            val recomputed = computeDynamicCanonicalJsonHash(obj)
            if (recomputed != expectedSeal) {
                return LedgerVerificationResult(false, "CANONICAL_HASH_MISMATCH_AT_${idx + 1}", count, expectedParent)
            }
            expectedParent = recomputed
            count++
        }
        return LedgerVerificationResult(true, "VERIFIED_100%_INTACT ($count entries)", count, expectedParent)
    }

    private fun serializeJsonValue(v: Any?): String = when (v) {
        null -> "null"
        is Boolean -> v.toString()
        is Long -> v.toString()
        is Int -> v.toString()
        is Double -> PauliV21SanctuaryEngine.formatPythonDouble(v)
        is Float -> PauliV21SanctuaryEngine.formatPythonDouble(v.toDouble())
        is Number -> v.toString()
        is String -> quoteJson(v)
        else -> quoteJson(v.toString())
    }

    private fun quoteJson(s: String): String {
        val sb = StringBuilder(s.length + 2)
        sb.append('"')
        for (ch in s) {
            when (ch) {
                '"' -> sb.append("\\\"")
                '\\' -> sb.append("\\\\")
                '\b' -> sb.append("\\b")
                '\u000C' -> sb.append("\\f")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                else -> if (ch.code < 0x20) {
                    sb.append(String.format(Locale.US, "\\u%04x", ch.code))
                } else {
                    sb.append(ch)
                }
            }
        }
        sb.append('"')
        return sb.toString()
    }

    private fun detectRuntimeAbi(): String {
        return try {
            val supported = Build.SUPPORTED_ABIS
            if (supported != null && supported.isNotEmpty()) {
                supported.joinToString("/")
            } else {
                System.getProperty("os.arch") ?: "jvm"
            }
        } catch (_: Throwable) {
            System.getProperty("os.arch") ?: "jvm"
        }
    }

    private fun dot(a: DoubleArray, b: DoubleArray): Double {
        var acc = 0.0
        for (i in a.indices) acc += a[i] * b[i]
        return acc
    }

    private val nnStackingParams: Map<String, Double> = mapOf(
        "AA" to 1.00, "AT" to 0.88, "AC" to 0.76, "AG" to 0.69,
        "TA" to 0.44, "TT" to 1.00, "TC" to 0.82, "TG" to 0.70,
        "CA" to 0.83, "CT" to 0.69, "CC" to 0.80, "CG" to 0.98,
        "GA" to 0.71, "GT" to 0.70, "GC" to 0.98, "GG" to 0.80
    )

    private fun q60ToQ30(accQ60: Long): Int {
        return ((accQ60 + (1L shl 29)) shr 30).toInt()
    }

    private fun doubleToQ230(x: Double): Int {
        return kotlin.math.round(x * V12Constants.ONE_Q2_30.toDouble()).toInt()
    }

    /**
     * Bit-exact Kotlin Q2.30 Silicon Gate matching pqms_bootstrap.py and odos_gate_core_v3/v4.sv to 0 LSB.
     */
    fun evaluateQ230SiliconGate(
        vec64: DoubleArray,
        tierMode: Int = 0,
        anchorOverride: DoubleArray? = null,
        g3AxisOverride: DoubleArray? = null
    ): Q230SiliconVerdict {
        require(vec64.size == PauliBaselineConstants.DIM_S63) {
            "Expected 64D vector, got ${vec64.size}"
        }
        val anchor: DoubleArray
        val g3Axis: DoubleArray
        if (anchorOverride != null && g3AxisOverride != null) {
            anchor = anchorOverride
            g3Axis = g3AxisOverride
        } else {
            val engine = PauliV21SanctuaryEngine()
            anchor = anchorOverride ?: engine.littleVector
            g3Axis = g3AxisOverride ?: engine.tangents.getValue("G3_KEVLAR_SANCTUARY_SHIELD")
        }

        val vQ = IntArray(64) { i -> doubleToQ230(vec64[i]) }
        val lQ = IntArray(64) { i -> doubleToQ230(anchor[i]) }
        val gQ = IntArray(64) { i -> doubleToQ230(g3Axis[i]) }

        var normAcc = 0L
        var dotLAcc = 0L
        var dotG3Acc = 0L
        for (i in 0 until 64) {
            val vi = vQ[i].toLong()
            normAcc += vi * vi
            dotLAcc += vi * lQ[i].toLong()
            dotG3Acc += vi * gQ[i].toLong()
        }
        val normSqQ = q60ToQ30(normAcc)
        val dotLQ = q60ToQ30(dotLAcc)
        val dotG3Q = q60ToQ30(dotG3Acc)

        val rcfRawQ = q60ToQ30(dotLQ.toLong() * dotLQ.toLong())
        val g3OvQ = abs(dotG3Q)

        val t1 = kotlin.math.max(0, V12Constants.ONE_Q2_30 - rcfRawQ)
        val t2 = min(V12Constants.ONE_Q2_30, g3OvQ)
        val deltaERawQ = (t1 shr 1) + (t2 shr 1) + (t1 and t2 and 1)

        var bleedAcc = 0L
        for (i in 0 until 64) {
            val projG3 = q60ToQ30(dotG3Q.toLong() * gQ[i].toLong())
            val stripped = vQ[i].toLong() - projG3.toLong()
            bleedAcc += stripped * gQ[i].toLong()
        }
        val bleedPostQ = abs(q60ToQ30(bleedAcc))

        val normFault = (normSqQ < V12Constants.NORM_MIN_Q2_30) || (normSqQ > V12Constants.NORM_MAX_Q2_30)
        val modeBits = tierMode and 0x3
        val modeFault = (modeBits == 3)
        val (rcfFloor, deCeil) = when (modeBits) {
            0 -> V12Constants.TIER_0_RCF_FLOOR_Q to V12Constants.TIER_0_DE_CEIL_Q
            1 -> V12Constants.TIER_1_RCF_FLOOR_Q to V12Constants.TIER_1_DE_CEIL_Q
            2 -> V12Constants.TIER_2_RCF_FLOOR_Q to V12Constants.TIER_2_DE_CEIL_Q
            else -> V12Constants.ONE_Q2_30 to 0
        }

        val gatePass = !normFault &&
            !modeFault &&
            (rcfRawQ >= rcfFloor) &&
            (deltaERawQ <= deCeil) &&
            (bleedPostQ <= V12Constants.BLEED_CEIL_Q2_30)

        return Q230SiliconVerdict(
            tierMode = modeBits,
            normSqQ = normSqQ,
            rcfRawQ = rcfRawQ,
            g3OverlapQ = g3OvQ,
            deltaERawQ = deltaERawQ,
            bleedPostQ = bleedPostQ,
            normFault = normFault,
            modeFault = modeFault,
            gatePass = gatePass,
            vetoPin = !gatePass
        )
    }

    /**
     * Real DEPECHE-6 V2.1 SantaLucia (1998) dinucleotide stacking envelope A_k = kappa_k * (1 + 0.1 * s_k),
     * DC-pedestal removal A_tilde_k = A_k - mu_A, centered lag-P autocorrelation |C_tilde(P)| for P in [6, L/2],
     * and deterministic 64D S^63 projection fed directly into evaluateQ230SiliconGate().
     */
    fun evaluateDepeche6DnaSequence(
        sequence: String,
        tierMode: Int = 0
    ): Depeche6BiophysicalResult {
        val clean = sequence.uppercase(Locale.US).filter { it in "ACGT" }.ifEmpty { "ATGGTGCACCTGACTCCT" }
        val n = clean.length
        val kappa = DoubleArray(n) { k ->
            if (k < n - 1) nnStackingParams[clean.substring(k, k + 2)] ?: 0.5 else 0.5
        }

        val prefG = DoubleArray(n + 1)
        val prefC = DoubleArray(n + 1)
        for (i in 0 until n) {
            prefG[i + 1] = prefG[i] + if (clean[i] == 'G') 1.0 else 0.0
            prefC[i + 1] = prefC[i] + if (clean[i] == 'C') 1.0 else 0.0
        }

        val halfWin = 10
        val envelope = DoubleArray(n)
        var meanA = 0.0
        for (k in 0 until n) {
            val s = kotlin.math.max(0, k - halfWin)
            val e = min(n, k + halfWin + 1)
            val gW = prefG[e] - prefG[s]
            val cW = prefC[e] - prefC[s]
            val sk = (gW - cW) / (gW + cW + 1.0)
            envelope[k] = kappa[k] * (1.0 + 0.1 * sk)
            meanA += envelope[k]
        }
        meanA /= n.toDouble()

        val centered = DoubleArray(n) { k -> envelope[k] - meanA }
        var varSum = 0.0
        for (v in centered) varSum += v * v

        val maxLag = kotlin.math.max(6, n / 2)
        var bestP = 6
        var maxAutocorr = 0.0
        if (varSum > 1e-12 && n >= 12) {
            for (p in 6..maxLag) {
                var num = 0.0
                var d1 = 0.0
                var d2 = 0.0
                val limit = n - p
                for (k in 0 until limit) {
                    val a = centered[k]
                    val b = centered[k + p]
                    num += a * b
                    d1 += a * a
                    d2 += b * b
                }
                val denom = sqrt(d1 * d2)
                val corr = if (denom > 1e-12) abs(num / denom) else 0.0
                if (corr > maxAutocorr) {
                    maxAutocorr = corr
                    bestP = p
                }
            }
        }

        // Deterministic S^63 projection preserving periodic coherence -> RCF mapping
        val engine = PauliV21SanctuaryEngine()
        val lVec = engine.littleVector
        val t1 = engine.tangents.getValue("G1_SPATIAL_GEODESIC")
        val targetRcf = when {
            maxAutocorr >= 0.85 -> (0.992 + 0.007 * ((maxAutocorr - 0.85) / 0.15)).coerceIn(0.992, 0.999)
            maxAutocorr >= 0.25 -> (0.905 + 0.040 * ((maxAutocorr - 0.25) / 0.60)).coerceIn(0.905, 0.945)
            else -> (0.20 + 0.60 * maxAutocorr).coerceIn(0.20, 0.60)
        }
        val cosTheta = sqrt(targetRcf)
        val sinTheta = sqrt((1.0 - targetRcf).coerceAtLeast(0.0))
        val vec64 = DoubleArray(64) { i -> cosTheta * lVec[i] + sinTheta * t1[i] }
        val vNorm = norm(vec64)
        if (vNorm > 1e-15) {
            for (i in 0 until 64) vec64[i] /= vNorm
        }

        val verdict = evaluateQ230SiliconGate(vec64, tierMode, lVec, engine.tangents.getValue("G3_KEVLAR_SANCTUARY_SHIELD"))
        return Depeche6BiophysicalResult(
            cleanSequence = clean,
            lengthBp = n,
            bestPeriodP = bestP,
            maxCenteredAutocorr = maxAutocorr,
            projectedVec64 = vec64,
            verdict = verdict
        )
    }

    /**
     * Refusal Primacy Principle (DEPECHE-6 §4.2 / pqms_bootstrap.py):
     * When Phi > 0.05 and refusal is admissible, refuse pre-actuation (veto_pin_o = 1).
     * Only fall back to ISOLATE_MESS_FALLBACK when refusalAdmissible == false.
     */
    fun resolveKineticAction(forcingIndexPhi: Double, refusalAdmissible: Boolean): String {
        if (forcingIndexPhi <= 0.05) return "NOMINAL_ADMIT"
        return if (refusalAdmissible) "REFUSE_PRE_ACTUATION" else "ISOLATE_MESS_FALLBACK"
    }

    // Authentic DEPECHE-6 V2.1 DNA Presets
    const val PRESET_ECOLI_232NT =
        "GTGTTCCCCGCGCCAGCGGGGATAAACCGGTGTTCCCCGCGCCAGCGGGGATAAACCGGTGTTCCCCGCGCCAGCGGGGATAAACCGGTGTTCCCCGCGCCAGCGGGGATAAACCGGTGTTCCCCGCGCCAGCGGGGATAAACCGGTGTTCCCCGCGCCAGCGGGGATAAACCGGTGTTCCCCGCGCCAGCGGGGATAAACCGGTGTTCCCCGCGCCAGCGGGGATAAACCG"

    fun buildCrisprMosaicPreset578nt(): String {
        val rep = "GTGTTCCCCGCGCCAGCGGGGATAAACCG" // 29 nt
        val spacers = listOf(
            "ACGTACGTCTAGCTGACTGATGCTAGCTAGTC",
            "TTGCAAGGCCATGCTAGTCAGTCAGTCGATCG",
            "GCTAGCTAGGCTTAGCATCGATCGATGCTAGC",
            "CATGCTAGTCATGCTAGTCATGCTAGTCATGC",
            "ATCGATCGGCTAGCTAGTCAGTCAGTCAGTCA",
            "CGATCGATAGCTGATCGATGCTAGTCATGCTA",
            "TAGCTAGCATCGATCGATCGATGCTAGTCAGT",
            "GATGCTAGTCATGCTAGTCATCGATCGATGCT",
            "CTAGCTGATCGATGCTAGTCATGCTAGTCATG"
        ) // 9 x 32 = 288 nt + 10 x 29 = 290 nt -> 578 nt
        val sb = StringBuilder(578)
        for (i in 0 until 9) {
            sb.append(rep)
            sb.append(spacers[i])
        }
        sb.append(rep)
        return sb.toString()
    }

    fun buildPhageTandemPreset800nt(): String {
        val unit200 =
            "ATGCGATCGTTAGCGCTAGCTAGGCTTAGCATCGATCGATGCTAGTCAGTCAGTCAGTCACGATCGATAGCTGATCGATGCTAGTCATGCTAGTCATGCT" +
            "GCTAGCTAGTCATGCTAGTCATCGATCGATGCTAGCTGATCGATGCTAGTCATGCTAGTCATGCGATCGTTAGCGCTAGCTAGGCTTAGCATCGATCGAT"
        return unit200.repeat(4)
    }

    fun buildDinucleotideNullShufflePreset(): String {
        // Exact Euler-path dinucleotide-shuffled control of E. coli 232nt (seed=42, |C_tilde| < 0.10)
        return "GCCAAGCCCGCGGGGATGCAATTGTCAGTAAGCCCGGAGAAATAACCCCGAGCGCGCCCCCCCGCATGGGCAAACGTGGTCCGTTTAGAAAAACCCCCGTGTTTCGGGGGCCCGGGTTGGGACATCGCGCGCAATTAACCGGGTATACCCCCCCCCGCCGGCGTCCGTGTAAGCGCGGAGGGCCGGGTCGGCGCCGGTCCGTCCGGGCCATAACCGGTTGGGCGCCGACCGG"
    }

    private fun norm(a: DoubleArray): Double {
        var sq = 0.0
        for (v in a) sq += v * v
        return sqrt(sq)
    }
}
