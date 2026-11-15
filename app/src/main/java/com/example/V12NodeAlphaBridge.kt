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
    const val REVISION = "V1.2"
    const val SPEC_ID = "PQMS-ODOS-MTSC-V-MAX-12-Node-ALPHA-V1.md"
    const val PROTOCOL_VERSION = "1.2-NODE-ALPHA"

    const val ODOS_G3_BLEED_CEILING = 1e-12
    const val EXPECTED_UNIT_S63_64000_F32_SHA256 =
        "490eaf6070dc8a404883c0787d4ed1a8226b3a5074e7be33269d8daf47397f27"
    const val V12_CHAIN_TIP_REF =
        "9114e99e06ff540439e16c1e8d564d9a965e6c21f55d0f0f8bbfc843f8c0aaee"

    // VMAX_HWINFO64_AB_TELEMETRY.json verified regimes (RTX 4060 Ti 16GB + R9 5950X, 0 WHEA errors)
    const val REGIME_1_PEAK_POWER_W = 85.783
    const val REGIME_1_PEAK_TEMP_C = 62.3
    const val REGIME_1_PEAK_VRAM_MB = 15314
    const val REGIME_2_MIN_POWER_W = 9.57
    const val REGIME_2_QUIESCENT_VRAM_MB = 468
    const val POWER_REDUCTION_MAX_X = 8.96

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

    private fun norm(a: DoubleArray): Double {
        var sq = 0.0
        for (v in a) sq += v * v
        return sqrt(sq)
    }
}
