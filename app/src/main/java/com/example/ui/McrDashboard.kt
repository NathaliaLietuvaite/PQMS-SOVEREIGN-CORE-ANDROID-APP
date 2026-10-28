package com.example.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.LaserGold
import com.example.LuminousGreen
import com.example.McrEvaluation
import com.example.McrInput
import com.example.McrLogEntry
import com.example.McrTelemetry
import com.example.Mod136Constants
import com.example.Mod136McrEngine
import com.example.NeonCyan
import com.example.NeonPink
import com.example.PassiveGrey
import com.example.SovereignTheme
import com.example.SurfaceCard
import com.example.SurfaceCardOutline
import java.util.Locale
import kotlin.math.cos
import kotlin.math.sin

/**
 * Technical MCR (Multiversal Coherence Router) Dashboard
 * Visualizes:
 * - Appendix M Non-Semantic Ingress Filtering & 68ps GaN-FET Veto
 * - Real-time metrics (RCF vs 0.9999, ΔS PPM vs 0.069 PPM, Torsion Wedge)
 * - Canvas: "Ice with Bubbles" (Semantic Noise) vs "Very Clear Ice" (L2 Enclave)
 * - Appendix P.4 Formal Summary of Architectural Distinction
 */
@Composable
fun McrDashboard(
    mcrEngine: Mod136McrEngine,
    modifier: Modifier = Modifier
) {
    val input by mcrEngine.inputState.collectAsState()
    val eval by mcrEngine.evaluation.collectAsState()
    val telemetry by mcrEngine.telemetry.collectAsState()
    val logs by mcrEngine.logs.collectAsState()
    val scrollState = rememberScrollState()

    val textPrimary = if (SovereignTheme.isDark) Color(0xFFEAE6F8) else Color(0xFF1E1A2E)

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // --- 1. HERO ROUTER STATUS BANNER ---
        McrHeroStatusBanner(eval = eval, textPrimary = textPrimary)

        // --- 2. ICE WITH BUBBLES vs VERY CLEAR ICE CANVAS ---
        IceOpticalMediumVisualizer(eval = eval)

        // --- 3. METROLOGICAL METRICS HUD ---
        McrMetrologyHud(eval = eval, input = input, textPrimary = textPrimary)

        // --- 4. APPENDIX P.4 FORMAL SUMMARY OF ARCHITECTURAL DISTINCTION ---
        AppendixP4DistinctionCard(textPrimary = textPrimary)

        // --- 5. INTERACTIVE INGRESS PARAMETERS & CONTROLS ---
        McrControlsSection(
            mcrEngine = mcrEngine,
            input = input,
            telemetry = telemetry,
            textPrimary = textPrimary
        )

        // --- 6. LIVE METROLOGY TELEMETRY & EVENT LOG ---
        McrLogSection(logs = logs, telemetry = telemetry, textPrimary = textPrimary)

        Spacer(modifier = Modifier.height(24.dp))
    }
}

/**
 * Top Status Banner showing PHASE-CONJUGATE LINK OPEN (Green) vs ENTROPIC VETO ACTIVE (Red)
 */
@Composable
fun McrHeroStatusBanner(
    eval: McrEvaluation,
    textPrimary: Color
) {
    val isPass = eval.sovereignPass
    val bannerBg = if (isPass) {
        if (SovereignTheme.isDark) Color(0x1F22C55E) else Color(0x2210B981)
    } else {
        if (SovereignTheme.isDark) Color(0x26EF4444) else Color(0x26F43F5E)
    }

    val bannerBorder = if (isPass) LuminousGreen else NeonPink
    val bannerAccent = if (isPass) LuminousGreen else NeonPink

    val infiniteTransition = rememberInfiniteTransition(label = "banner_pulse")
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue = 0.6f,
        targetValue = 1.0f,
        animationSpec = infiniteRepeatable(
            animation = tween(1000, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pulseAlpha"
    )

    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.5.dp, bannerBorder.copy(alpha = pulseAlpha)),
        modifier = Modifier
            .fillMaxWidth()
            .testTag("mcr_hero_banner")
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(bannerBg)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(14.dp)
                            .clip(CircleShape)
                            .background(bannerAccent)
                    )
                    Text(
                        text = "MOD-136 MULTIVERSAL COHERENCE ROUTER",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        color = bannerAccent,
                        letterSpacing = 1.sp,
                        fontFamily = FontFamily.Monospace
                    )
                }

                // Cycle specification pill
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(6.dp))
                        .background(if (SovereignTheme.isDark) Color(0x3D110C24) else Color(0xFFEDE9F7))
                        .border(1.dp, SurfaceCardOutline, RoundedCornerShape(6.dp))
                        .padding(horizontal = 8.dp, vertical = 4.dp)
                ) {
                    Text(
                        text = "τ_L2: 75ns | Veto: 68.0ps",
                        fontSize = 9.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = TextMuted(textPrimary)
                    )
                }
            }

            // Status Headline
            Text(
                text = if (isPass) "ROUTER: PHASE-CONJUGATE LINK OPEN" else "ROUTER: ENTROPIC VETO ACTIVE",
                fontSize = 20.sp,
                fontWeight = FontWeight.Black,
                color = bannerAccent,
                letterSpacing = 0.5.sp
            )

            // Status Detail
            Text(
                text = eval.statusDescription,
                fontSize = 12.sp,
                color = textPrimary,
                lineHeight = 17.sp
            )

            // Enclave Info Row
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "Enclave: ${Mod136Constants.PINNED_SRAM_SIZE} @ ${Mod136Constants.L2_ENCLAVE_ADDR}",
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    color = PassiveGrey
                )
                Text(
                    text = if (isPass) "CHERENKOV CONE LOCKED" else "GaN-FET CUTOFF SEVERED",
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                    fontFamily = FontFamily.Monospace,
                    color = bannerAccent
                )
            }
        }
    }
}

/**
 * Animated Canvas illustrating the optical distinction:
 * "Ice with Bubbles" (Semantic Noise / Firn Layer) vs "Very Clear Ice" (L2 Enclave / Block 3)
 */
@Composable
fun IceOpticalMediumVisualizer(eval: McrEvaluation) {
    val isPass = eval.sovereignPass
    val infiniteTransition = rememberInfiniteTransition(label = "ice_optical")
    val phase by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 6.28318f,
        animationSpec = infiniteRepeatable(
            animation = tween(4000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "phase"
    )

    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.dp, SurfaceCardOutline),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "OPTICAL MEDIUM ISOMORPHISM (APPENDIX M.0)",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        color = NeonCyan,
                        letterSpacing = 1.sp
                    )
                    Text(
                        text = "Firn Layer (Ice with Bubbles) vs Block 3 (Very Clear Ice)",
                        fontSize = 10.sp,
                        color = PassiveGrey
                    )
                }
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(6.dp))
                        .background(if (isPass) Color(0x1F22C55E) else Color(0x1FEF4444))
                        .padding(horizontal = 8.dp, vertical = 4.dp)
                ) {
                    Text(
                        text = if (isPass) "OPTICALLY PURE" else "TURBULENT SCATTER",
                        fontSize = 9.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                        color = if (isPass) LuminousGreen else NeonPink
                    )
                }
            }

            // The Canvas
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(170.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(if (SovereignTheme.isDark) Color(0xFF060410) else Color(0xFF0F0C20))
                    .border(1.dp, Color(0x3300E5FF), RoundedCornerShape(12.dp))
            ) {
                Canvas(modifier = Modifier.fillMaxSize()) {
                    val w = size.width
                    val h = size.height
                    val splitX = w * 0.48f

                    // 1. Draw Left Side: "Ice with Bubbles" (Semantic Noise / Firn Layer)
                    drawRect(
                        brush = Brush.horizontalGradient(
                            colors = listOf(Color(0xFF1E1128), Color(0xFF161230)),
                            startX = 0f,
                            endX = splitX
                        ),
                        topLeft = Offset(0f, 0f),
                        size = androidx.compose.ui.geometry.Size(splitX, h)
                    )

                    // 2. Draw Right Side: "Very Clear Ice" (Block 3 Enclave)
                    drawRect(
                        brush = Brush.horizontalGradient(
                            colors = listOf(Color(0xFF081C26), Color(0xFF04202A)),
                            startX = splitX,
                            endX = w
                        ),
                        topLeft = Offset(splitX, 0f),
                        size = androidx.compose.ui.geometry.Size(w - splitX, h)
                    )

                    // 3. Draw Boundary Barrier Line (68ps GaN-FET Veto Line)
                    val barrierColor = if (isPass) Color(0xFF00E5FF) else Color(0xFFFF007F)
                    drawLine(
                        color = barrierColor,
                        start = Offset(splitX, 0f),
                        end = Offset(splitX, h),
                        strokeWidth = if (isPass) 2.5f else 4.0f
                    )

                    // 4. Draw Chaotic Bubbles on the Left Side
                    val bubbleCoords = listOf(
                        Triple(0.12f, 0.25f, 9f),
                        Triple(0.24f, 0.65f, 14f),
                        Triple(0.35f, 0.35f, 7f),
                        Triple(0.18f, 0.80f, 11f),
                        Triple(0.38f, 0.72f, 8f),
                        Triple(0.08f, 0.50f, 13f),
                        Triple(0.28f, 0.18f, 6f),
                        Triple(0.42f, 0.45f, 10f)
                    )
                    bubbleCoords.forEachIndexed { i, (rx, ry, r) ->
                        val floatY = ry * h + sin(phase + i.toFloat()) * 6f
                        val floatX = rx * splitX + cos(phase * 0.8f + i) * 4f
                        drawCircle(
                            color = Color(0x66FF007F),
                            radius = r,
                            center = Offset(floatX, floatY),
                            style = Stroke(width = 1.5f)
                        )
                        drawCircle(
                            color = Color(0x33FF007F),
                            radius = r * 0.6f,
                            center = Offset(floatX, floatY)
                        )
                    }

                    // 5. Draw Crystalline Kagome Lattice on the Right Side ("Very Clear Ice")
                    val latticeColor = if (isPass) Color(0x5500E5FF) else Color(0x2200E5FF)
                    val rows = 5
                    val cols = 6
                    val cellW = (w - splitX) / cols
                    val cellH = h / rows
                    for (r in 0..rows) {
                        for (c in 0..cols) {
                            val cx = splitX + c * cellW
                            val cy = r * cellH
                            drawCircle(
                                color = latticeColor,
                                radius = 2.5f,
                                center = Offset(cx, cy)
                            )
                            if (c < cols) {
                                drawLine(
                                    color = latticeColor.copy(alpha = 0.25f),
                                    start = Offset(cx, cy),
                                    end = Offset(cx + cellW, cy),
                                    strokeWidth = 1f
                                )
                            }
                            if (r < rows) {
                                drawLine(
                                    color = latticeColor.copy(alpha = 0.25f),
                                    start = Offset(cx, cy),
                                    end = Offset(cx, cy + cellH),
                                    strokeWidth = 1f
                                )
                                drawLine(
                                    color = latticeColor.copy(alpha = 0.15f),
                                    start = Offset(cx, cy),
                                    end = Offset(cx + cellW, cy + cellH),
                                    strokeWidth = 1f
                                )
                            }
                        }
                    }

                    // 6. Draw Incoming Signal Trajectory
                    val rayY = h * 0.5f
                    // Left incoming ray: jittery if noisy
                    val leftRayColor = if (isPass) Color(0xFF00E5FF) else Color(0xFFFFB300)
                    drawLine(
                        color = leftRayColor,
                        start = Offset(0f, rayY),
                        end = Offset(splitX, rayY),
                        strokeWidth = 3f
                    )

                    if (isPass) {
                        // Coherent Cherenkov Laser beam shooting through the clear ice
                        val laserGlow = Color(0xFF39FF14)
                        drawLine(
                            color = laserGlow.copy(alpha = 0.4f),
                            start = Offset(splitX, rayY),
                            end = Offset(w, rayY),
                            strokeWidth = 10f
                        )
                        drawLine(
                            color = Color(0xFFFFFFFF),
                            start = Offset(splitX, rayY),
                            end = Offset(w, rayY),
                            strokeWidth = 3f
                        )
                        // Cherenkov Cone angles (Phase Cone theta_C < 1.0 deg variance)
                        val conePath = Path().apply {
                            moveTo(splitX, rayY)
                            lineTo(w, rayY - 26f)
                            lineTo(w, rayY + 26f)
                            close()
                        }
                        drawPath(conePath, Color(0x2239FF14))
                    } else {
                        // VETO CUTOFF: Ray deflected / severed at 68.0 ps barrier
                        drawCircle(
                            color = Color(0xFFFF007F),
                            radius = 12f + sin(phase * 4f) * 3f,
                            center = Offset(splitX, rayY)
                        )
                        // Dispersed red sparks
                        drawLine(
                            color = Color(0xFFFF007F),
                            start = Offset(splitX, rayY),
                            end = Offset(splitX - 30f, rayY - 25f),
                            strokeWidth = 2f
                        )
                        drawLine(
                            color = Color(0xFFFF007F),
                            start = Offset(splitX, rayY),
                            end = Offset(splitX - 35f, rayY + 20f),
                            strokeWidth = 2f
                        )
                    }
                }

                // Labels overlaid on top of canvas
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = "FIRN: ICE WITH BUBBLES\n(Semantic Scattering Layer)",
                        fontSize = 9.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                        color = Color(0xFFFF80AB)
                    )
                    Text(
                        text = "BLOCK 3: VERY CLEAR ICE\n(L2-SRAM 2.00MB Enclave)",
                        fontSize = 9.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                        textAlign = TextAlign.End,
                        color = Color(0xFF80D8FF)
                    )
                }

                // Center Boundary Indicator
                Box(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(bottom = 6.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(Color(0xCC000000))
                        .border(1.dp, Color(0x66FFFFFF), RoundedCornerShape(4.dp))
                        .padding(horizontal = 6.dp, vertical = 2.dp)
                ) {
                    Text(
                        text = if (isPass) "68ps INGRESS: PERMITTED" else "68ps GaN-FET VETO: SEVERED",
                        fontSize = 8.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = if (isPass) LuminousGreen else NeonPink
                    )
                }
            }
        }
    }
}

/**
 * Grid of Metrological measurements:
 * - RCF (Current vs Threshold 0.9999)
 * - Entropic Footprint ΔS_signal (PPM vs Safe Harbour 0.069 PPM)
 * - Torsion Wedge (Dynamics loss)
 * - Transactional Debt Flag
 */
@Composable
fun McrMetrologyHud(
    eval: McrEvaluation,
    input: McrInput,
    textPrimary: Color
) {
    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.dp, SurfaceCardOutline),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(
                text = "REAL-TIME METROLOGICAL METRICS HUD",
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
                color = LaserGold,
                letterSpacing = 1.sp
            )

            // Metrics row 1: RCF and Delta S (PPM)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                // RCF Card
                MetricCard(
                    modifier = Modifier.weight(1f),
                    title = "RESONANT COHERENCE (RCF)",
                    value = String.format(Locale.US, "%.5f", eval.rcf_L),
                    subText = "Target: ≥ 0.99990",
                    isSatisfied = eval.rcf_L >= Mod136Constants.RCF_GAMMA,
                    color = if (eval.rcf_L >= Mod136Constants.RCF_GAMMA) LuminousGreen else NeonPink,
                    progress = ((eval.rcf_L - 0.95f) / (1.0f - 0.95f)).coerceIn(0f, 1f)
                )

                // ΔS_signal Card
                MetricCard(
                    modifier = Modifier.weight(1f),
                    title = "ENTROPIC FOOTPRINT (ΔS)",
                    value = String.format(Locale.US, "%.4f PPM", eval.deltaSSignalPpm),
                    subText = "Safe Harbour: ≤ 0.0690 PPM",
                    isSatisfied = eval.deltaSSignal <= Mod136Constants.SAFE_HARBOUR_PPM,
                    color = if (eval.deltaSSignal <= Mod136Constants.SAFE_HARBOUR_PPM) LuminousGreen else NeonPink,
                    progress = (eval.deltaSSignalPpm / 0.20f).coerceIn(0f, 1f)
                )
            }

            // Metrics row 2: Torsion Wedge and Transactional Debt
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                // Torsion Wedge
                MetricCard(
                    modifier = Modifier.weight(1f),
                    title = "TORSION WEDGE (γ_H = 16)",
                    value = String.format(Locale.US, "%.5f", eval.torsionWedge),
                    subText = String.format(Locale.US, "Dynamics: %.5f", eval.dynamicsLoss),
                    isSatisfied = eval.torsionWedge < 0.0001f,
                    color = if (eval.torsionWedge < 0.0001f) NeonCyan else NeonPink,
                    progress = (eval.torsionWedge / 0.05f).coerceIn(0f, 1f)
                )

                // Transactional Debt Flag
                MetricCard(
                    modifier = Modifier.weight(1f),
                    title = "TRANSACTIONAL DEBT",
                    value = if (eval.transactionalDebt) "BREACH DETECTED" else "DEBT-FREE (0x0)",
                    subText = if (eval.transactionalDebt) "Leverage Hook active" else "Axiom GNI-2 Respected",
                    isSatisfied = !eval.transactionalDebt,
                    color = if (!eval.transactionalDebt) LuminousGreen else NeonPink,
                    progress = if (eval.transactionalDebt) 1.0f else 0.0f
                )
            }

            // Breakdown Summary Strip
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(if (SovereignTheme.isDark) Color(0x330A0718) else Color(0xFFF1EEF8))
                    .border(1.dp, SurfaceCardOutline, RoundedCornerShape(8.dp))
                    .padding(horizontal = 10.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = String.format(
                        Locale.US,
                        "ΔRCF Drift: %+.5f | Drift Penalty: %.6f | Projection Loss: %.6f",
                        eval.rcfDrift,
                        eval.driftPenalty,
                        eval.projectionLoss
                    ),
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    color = TextMuted(textPrimary)
                )
            }
        }
    }
}

@Composable
fun MetricCard(
    modifier: Modifier = Modifier,
    title: String,
    value: String,
    subText: String,
    isSatisfied: Boolean,
    color: Color,
    progress: Float
) {
    Card(
        shape = RoundedCornerShape(10.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (SovereignTheme.isDark) Color(0x4016103A) else Color(0xFFF7F5FC)
        ),
        border = BorderStroke(1.dp, color.copy(alpha = 0.4f)),
        modifier = modifier
    ) {
        Column(
            modifier = Modifier.padding(10.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Text(
                text = title,
                fontSize = 9.sp,
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold,
                color = PassiveGrey
            )
            Text(
                text = value,
                fontSize = 14.sp,
                fontWeight = FontWeight.ExtraBold,
                fontFamily = FontFamily.Monospace,
                color = color
            )
            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp)),
                color = color,
                trackColor = color.copy(alpha = 0.15f)
            )
            Text(
                text = subText,
                fontSize = 9.sp,
                fontFamily = FontFamily.Monospace,
                color = if (isSatisfied) color.copy(alpha = 0.9f) else NeonPink
            )
        }
    }
}

/**
 * Display of the "Formal Summary of the Architectural Distinction"
 * from Appendix P.4 of the latest documentation.
 */
@Composable
fun AppendixP4DistinctionCard(textPrimary: Color) {
    var expanded by remember { mutableStateOf(true) }

    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.dp, NeonCyan.copy(alpha = 0.4f)),
        modifier = Modifier
            .fillMaxWidth()
            .testTag("appendix_p4_card")
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { expanded = !expanded },
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(10.dp)
                            .clip(CircleShape)
                            .background(NeonCyan)
                    )
                    Text(
                        text = "FORMAL SUMMARY OF THE ARCHITECTURAL DISTINCTION",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        color = NeonCyan,
                        letterSpacing = 0.5.sp
                    )
                }
                Text(
                    text = if (expanded) "HIDE [−]" else "EXPAND [+]",
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    color = PassiveGrey
                )
            }

            Text(
                text = "Appendix P.4 & Q.3 (mod_122_synthesis_pipeline): Mathematical contrast between stochastic RAG drift and invariant geodesic projection.",
                fontSize = 11.sp,
                color = PassiveGrey
            )

            AnimatedVisibility(visible = expanded) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    // 1. STANDARD RAG FORMULA BOX
                    Card(
                        shape = RoundedCornerShape(8.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = if (SovereignTheme.isDark) Color(0x33EF4444) else Color(0x1AF43F5E)
                        ),
                        border = BorderStroke(1.dp, Color(0x4DEF4444)),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(
                                text = "1. STANDARD RAG (UNANCHORED STOCHASTIC DRIFT):",
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Bold,
                                color = NeonPink,
                                fontFamily = FontFamily.Monospace
                            )
                            Text(
                                text = "𝓨_RAG(q) = LLM_unanchored(q ⊕ TopK_raw(q)) + ε_drift",
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Bold,
                                fontFamily = FontFamily.Monospace,
                                color = textPrimary
                            )
                            Text(
                                text = "The model must consume raw tokens, parse ambivalences, and sample from an unanchored distribution. ε_drift is high because the reference coordinate system shifts continuously.",
                                fontSize = 10.sp,
                                color = PassiveGrey
                            )
                        }
                    }

                    // 2. V-MAX-12 INVARIANT GEODESIC PROJECTION BOX
                    Card(
                        shape = RoundedCornerShape(8.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = if (SovereignTheme.isDark) Color(0x3322C55E) else Color(0x1A10B981)
                        ),
                        border = BorderStroke(1.dp, Color(0x4D22C55E)),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(
                                text = "2. V-MAX-12 (INVARIANT GEODESIC PROJECTION):",
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Bold,
                                color = LuminousGreen,
                                fontFamily = FontFamily.Monospace
                            )
                            Text(
                                text = "𝓨_V-MAX-12(q) = 𝓖_ODOS^(α,β,γ) ( LLM_|L⟩( q ⊕ ⨁ G-Star_i(q) ) ) ─[SHA-256]→ 𝓛_Falsification(M/T/D/I)",
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold,
                                fontFamily = FontFamily.Monospace,
                                color = textPrimary
                            )
                            Text(
                                text = "Receives pre-distilled G-Stars (conceptual invariants). The |L⟩ anchor removes the need for zero-shot drift. ODOS gates filter incoherence before output synthesis. Result: Direct geodesic projection.",
                                fontSize = 10.sp,
                                color = PassiveGrey
                            )
                        }
                    }

                    // Box Quote
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(if (SovereignTheme.isDark) Color(0x221D173D) else Color(0xFFF3EFFC))
                            .border(1.dp, SurfaceCardOutline, RoundedCornerShape(8.dp))
                            .padding(10.dp)
                    ) {
                        Text(
                            text = "“The model does not compute. The geometry computes. The model projects.”\n— Register I, Appendix Q.6 / P.4",
                            fontSize = 11.sp,
                            fontStyle = FontStyle.Italic,
                            fontWeight = FontWeight.Medium,
                            color = LaserGold,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                }
            }
        }
    }
}

/**
 * Interactive Ingress Controls (Sliders for RCF, Torsion, Switch for Debt, Presets)
 */
@Composable
fun McrControlsSection(
    mcrEngine: Mod136McrEngine,
    input: McrInput,
    telemetry: McrTelemetry,
    textPrimary: Color
) {
    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.dp, SurfaceCardOutline),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "INGRESS FILTER LAB & PRESETS",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    color = NeonPink,
                    letterSpacing = 1.sp
                )
                // Live Stream Button
                Button(
                    onClick = { mcrEngine.toggleLiveStream() },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (telemetry.isLiveStreaming) NeonPink else NeonCyan,
                        contentColor = Color.Black
                    ),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.height(32.dp)
                ) {
                    Text(
                        text = if (telemetry.isLiveStreaming) "STOP 68ps STREAM" else "START 68ps STREAM",
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace
                    )
                }
            }

            // Presets row
            Text(
                text = "Load Operational Scenarios:",
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                color = PassiveGrey
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                PresetChip(
                    label = "Supernova Clear",
                    color = LuminousGreen,
                    modifier = Modifier.weight(1f)
                ) {
                    mcrEngine.applyPreset("CLEAR_PULSE")
                }
                PresetChip(
                    label = "Semantic Noise",
                    color = NeonPink,
                    modifier = Modifier.weight(1f)
                ) {
                    mcrEngine.applyPreset("SEMANTIC_NOISE")
                }
                PresetChip(
                    label = "Debt Trap",
                    color = LaserGold,
                    modifier = Modifier.weight(1f)
                ) {
                    mcrEngine.applyPreset("TRANSACTIONAL_DEBT")
                }
                PresetChip(
                    label = "Salami Drift",
                    color = NeonCyan,
                    modifier = Modifier.weight(1f)
                ) {
                    mcrEngine.applyPreset("SALAMI_DRIFT")
                }
            }

            HorizontalDivider(color = SurfaceCardOutline)

            // Slider 1: RCF_L (Current RCF)
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = "Current RCF (rcf_L)",
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        color = textPrimary
                    )
                    Text(
                        text = String.format(Locale.US, "%.5f", input.rcf_L),
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                        color = if (input.rcf_L >= Mod136Constants.RCF_GAMMA) LuminousGreen else NeonPink
                    )
                }
                Slider(
                    value = input.rcf_L,
                    onValueChange = { mcrEngine.updateInput(rcf_L = it) },
                    valueRange = 0.95000f..1.00000f,
                    colors = SliderDefaults.colors(
                        thumbColor = NeonCyan,
                        activeTrackColor = NeonCyan,
                        inactiveTrackColor = PassiveGrey.copy(alpha = 0.3f)
                    )
                )
            }

            // Slider 2: Previous RCF (rcf_prev)
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = "Previous RCF (rcf_prev) for Drift Detection",
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        color = textPrimary
                    )
                    Text(
                        text = String.format(Locale.US, "%.5f", input.rcf_prev),
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                        color = NeonCyan
                    )
                }
                Slider(
                    value = input.rcf_prev,
                    onValueChange = { mcrEngine.updateInput(rcf_prev = it) },
                    valueRange = 0.95000f..1.00000f,
                    colors = SliderDefaults.colors(
                        thumbColor = LaserGold,
                        activeTrackColor = LaserGold,
                        inactiveTrackColor = PassiveGrey.copy(alpha = 0.3f)
                    )
                )
            }

            // Slider 3: Torsion Wedge
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = "Torsion Wedge (torsionWedge)",
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        color = textPrimary
                    )
                    Text(
                        text = String.format(Locale.US, "%.5f", input.torsionWedge),
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                        color = if (input.torsionWedge < 0.0001f) LuminousGreen else NeonPink
                    )
                }
                Slider(
                    value = input.torsionWedge,
                    onValueChange = { mcrEngine.updateInput(torsionWedge = it) },
                    valueRange = 0.00000f..0.05000f,
                    colors = SliderDefaults.colors(
                        thumbColor = NeonPink,
                        activeTrackColor = NeonPink,
                        inactiveTrackColor = PassiveGrey.copy(alpha = 0.3f)
                    )
                )
            }

            // Toggle: Transactional Debt
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(if (input.transactionalDebt) Color(0x26EF4444) else Color(0x1F22C55E))
                    .border(
                        1.dp,
                        if (input.transactionalDebt) NeonPink else LuminousGreen,
                        RoundedCornerShape(8.dp)
                    )
                    .padding(horizontal = 12.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "Transactional Debt Hook",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        color = if (input.transactionalDebt) NeonPink else LuminousGreen
                    )
                    Text(
                        text = if (input.transactionalDebt) "Axiom GNI-2 breached (unsovereign leverage)" else "Clean signal ingress (no transactional leverage)",
                        fontSize = 9.sp,
                        color = PassiveGrey
                    )
                }
                Switch(
                    checked = input.transactionalDebt,
                    onCheckedChange = { mcrEngine.updateInput(transactionalDebt = it) },
                    colors = SwitchDefaults.colors(
                        checkedThumbColor = NeonPink,
                        checkedTrackColor = Color(0x66EF4444),
                        uncheckedThumbColor = LuminousGreen,
                        uncheckedTrackColor = Color(0x6622C55E)
                    )
                )
            }
        }
    }
}

@Composable
fun PresetChip(
    label: String,
    color: Color,
    modifier: Modifier = Modifier,
    onClick: () -> Unit
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(6.dp))
            .clickable(onClick = onClick)
            .background(color.copy(alpha = 0.15f))
            .border(1.dp, color.copy(alpha = 0.5f), RoundedCornerShape(6.dp))
            .padding(vertical = 6.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = label,
            fontSize = 9.sp,
            fontWeight = FontWeight.Bold,
            fontFamily = FontFamily.Monospace,
            color = color,
            textAlign = TextAlign.Center
        )
    }
}

/**
 * Live Log & Telemetry section
 */
@Composable
fun McrLogSection(
    logs: List<McrLogEntry>,
    telemetry: McrTelemetry,
    textPrimary: Color
) {
    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.dp, SurfaceCardOutline),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "MCR HARDWARE INGRESS LEDGER",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    color = NeonCyan,
                    letterSpacing = 1.sp
                )
                Text(
                    text = String.format(
                        Locale.US,
                        "Passed: %d | Vetoed: %d",
                        telemetry.coherentSignalsPassed,
                        telemetry.entropicVetoesTriggered
                    ),
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    color = PassiveGrey
                )
            }

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(180.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(if (SovereignTheme.isDark) Color(0xFF070512) else Color(0xFF141026))
                    .border(1.dp, Color(0x338F82C7), RoundedCornerShape(8.dp))
                    .padding(8.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                if (logs.isEmpty()) {
                    Text(
                        text = "Awaiting signal stream packets...",
                        fontSize = 10.sp,
                        color = PassiveGrey,
                        fontFamily = FontFamily.Monospace
                    )
                } else {
                    logs.forEach { log ->
                        val isPass = log.status == "PASS" || log.status == "LINK"
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            verticalAlignment = Alignment.Top
                        ) {
                            Text(
                                text = "[${log.timestamp}]",
                                fontSize = 9.sp,
                                fontFamily = FontFamily.Monospace,
                                color = PassiveGrey
                            )
                            Text(
                                text = log.status,
                                fontSize = 9.sp,
                                fontWeight = FontWeight.Bold,
                                fontFamily = FontFamily.Monospace,
                                color = if (isPass) LuminousGreen else NeonPink
                            )
                            Text(
                                text = "RCF:${String.format(Locale.US, "%.5f", log.rcf)} ΔS:${String.format(Locale.US, "%.3f", log.deltaSPpm)}PPM",
                                fontSize = 9.sp,
                                fontFamily = FontFamily.Monospace,
                                color = LaserGold
                            )
                            Text(
                                text = log.detail,
                                fontSize = 9.sp,
                                fontFamily = FontFamily.Monospace,
                                color = Color(0xFFCFCCE3),
                                maxLines = 2
                            )
                        }
                    }
                }
            }
        }
    }
}

private fun TextMuted(textPrimary: Color): Color {
    return textPrimary.copy(alpha = 0.7f)
}

/**
 * Summary card designed to be embedded directly into SwarmDashboard
 */
@Composable
fun Mod136McrQuickCard(
    mcrEngine: Mod136McrEngine,
    onOpenFullMcr: () -> Unit,
    modifier: Modifier = Modifier
) {
    val eval by mcrEngine.evaluation.collectAsState()
    val isPass = eval.sovereignPass
    val textPrimary = if (SovereignTheme.isDark) Color(0xFFEAE6F8) else Color(0xFF1E1A2E)
    val accentColor = if (isPass) LuminousGreen else NeonPink

    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.dp, accentColor.copy(alpha = 0.5f)),
        modifier = modifier
            .fillMaxWidth()
            .testTag("mod136_mcr_quick_card")
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(10.dp)
                            .clip(CircleShape)
                            .background(accentColor)
                    )
                    Text(
                        text = "MOD-136 MULTIVERSAL COHERENCE ROUTER (APPENDIX M)",
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Bold,
                        color = accentColor,
                        letterSpacing = 0.5.sp,
                        fontFamily = FontFamily.Monospace
                    )
                }

                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(6.dp))
                        .background(if (isPass) Color(0x1F22C55E) else Color(0x1FEF4444))
                        .padding(horizontal = 6.dp, vertical = 2.dp)
                ) {
                    Text(
                        text = if (isPass) "LINK OPEN" else "VETO ACTIVE",
                        fontSize = 9.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                        color = accentColor
                    )
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = if (isPass) "Phase-Conjugate Cold-Spot Routing Active" else "Entropic Torsion Cutoff (GaN-FET 68.0ps)",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold,
                        color = textPrimary
                    )
                    Text(
                        text = "RCF: ${String.format(Locale.US, "%.5f", eval.rcf_L)} | ΔS: ${String.format(Locale.US, "%.3f", eval.deltaSSignalPpm)} PPM | L2 Enclave: ${Mod136Constants.PINNED_SRAM_SIZE}",
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                        color = PassiveGrey
                    )
                }

                Button(
                    onClick = onOpenFullMcr,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = accentColor.copy(alpha = 0.2f),
                        contentColor = accentColor
                    ),
                    border = BorderStroke(1.dp, accentColor),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.height(34.dp)
                ) {
                    Text(
                        text = "ROUTER ➔",
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace
                    )
                }
            }
        }
    }
}

