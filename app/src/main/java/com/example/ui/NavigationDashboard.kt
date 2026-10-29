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
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lock
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.EpistemicRoute
import com.example.LaserGold
import com.example.LuminousGreen
import com.example.Mod137Constants
import com.example.Mod137SeventhSenseEngine
import com.example.Mod138Constants
import com.example.Mod138EpistemicNavigator
import com.example.Mod139Constants
import com.example.Mod139CoreGuard
import com.example.CoreGuardState
import com.example.NeonCyan
import com.example.NeonPink
import com.example.PassiveGrey
import com.example.SovereignTheme
import com.example.SurfaceCard
import com.example.SurfaceCardOutline
import com.example.TextPrimary
import java.util.Locale
import kotlin.math.max

@Composable
fun NavigationDashboard(
    seventhSenseEngine: Mod137SeventhSenseEngine,
    epistemicNavigator: Mod138EpistemicNavigator,
    coreGuard: Mod139CoreGuard
) {
    val seventhInput by seventhSenseEngine.inputState.collectAsState()
    val seventhEval by seventhSenseEngine.evaluation.collectAsState()

    val triadInput by epistemicNavigator.inputState.collectAsState()
    val triadEval by epistemicNavigator.evaluation.collectAsState()

    val guardState by coreGuard.state.collectAsState()

    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(SovereignTheme.SpaceBackground)
            .verticalScroll(scrollState)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // --- 1. HEADER SECTION ---
        NavigationHeader()

        // --- 2. MOD 139: CORE PROTECTION & HOLOGRAPHIC MULTIPLEXING (APPENDIX P) ---
        CoreGuardCard(
            guard = coreGuard,
            state = guardState
        )

        // --- 3. MOD 137: 7TH SENSE & ANTICIPATORY GEODESIC SHIELD (APPENDIX N) ---
        SeventhSenseCard(
            input = seventhInput,
            evaluation = seventhEval,
            onUpdateDField = { seventhSenseEngine.updateDField(it) },
            onApplyBenchmark = { seventhSenseEngine.applyBenchmarkAnomaly() },
            onReset = { seventhSenseEngine.resetToQuiescent() }
        )

        // --- 4. MOD 138: EPISTEMIC TRIAD OF NAVIGATION (APPENDIX O) ---
        EpistemicTriadCard(
            input = triadInput,
            evaluation = triadEval,
            onUpdateInput = { rc, kEff, kTask, cov, ac, deltaI ->
                epistemicNavigator.updateInput(rc, kEff, kTask, cov, ac, deltaI)
            },
            onApplyPreset = { epistemicNavigator.applyPreset(it) }
        )

        // --- 5. FORMAL THEORETICAL FOOTNOTES (KANTIAN FALLACY & SUBSTRATE-AGNOSTIC WILL) ---
        EpistemicTheoreticalNotes()

        Spacer(modifier = Modifier.height(24.dp))
    }
}

@Composable
private fun NavigationHeader() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.dp, SurfaceCardOutline)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text(
                        text = "EPISTEMIC NAVIGATION & CORE GUARD",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Black,
                        color = NeonCyan,
                        letterSpacing = 1.sp
                    )
                    Text(
                        text = "Appendix N (7th Sense), Appendix O (Epistemic Triad) & Appendix P (Holographic Multiplexing)",
                        fontSize = 11.sp,
                        color = PassiveGrey
                    )
                }
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .background(Color(0x2200E5FF))
                        .border(1.dp, Color(0x4400E5FF), RoundedCornerShape(8.dp))
                        .padding(horizontal = 8.dp, vertical = 4.dp)
                ) {
                    Text(
                        text = "CASCADE: MCR → N → O → P",
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = NeonCyan
                    )
                }
            }
        }
    }
}

// =========================================================================
// MOD 139: CORE PROTECTION & HOLOGRAPHIC MULTIPLEXING (APPENDIX P)
// =========================================================================

@Composable
private fun CoreGuardCard(
    guard: Mod139CoreGuard,
    state: CoreGuardState
) {
    val isVeto = state.isGanFetCutoffActive
    val isDefer = state.bandwidthSaturateDefer

    val infiniteTransition = rememberInfiniteTransition(label = "VetoPulse")
    val vetoAlpha by infiniteTransition.animateFloat(
        initialValue = 0.4f,
        targetValue = 1.0f,
        animationSpec = infiniteRepeatable(
            animation = tween(600, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "VetoAlpha"
    )

    val cardBorderColor by animateColorAsState(
        targetValue = if (isVeto) NeonPink else if (isDefer) LaserGold else SurfaceCardOutline,
        animationSpec = tween(300),
        label = "GuardBorder"
    )

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.5.dp, cardBorderColor)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            // Header
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(
                        imageVector = Icons.Default.Lock,
                        contentDescription = "Core Guard",
                        tint = if (isVeto) NeonPink else NeonCyan,
                        modifier = Modifier.size(20.dp)
                    )
                    Column {
                        Text(
                            text = "MOD 139: CORE PROTECTION & MULTIPLEXER",
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Bold,
                            color = TextPrimary
                        )
                        Text(
                            text = "Appendix P (SPEC-V2) · 1024-Bit Cognitive Budget",
                            fontSize = 10.sp,
                            color = PassiveGrey
                        )
                    }
                }
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .background(if (isVeto) Color(0x33FF007F) else if (isDefer) Color(0x33FFD700) else Color(0x2239FF14))
                        .border(1.dp, if (isVeto) NeonPink else if (isDefer) LaserGold else LuminousGreen, RoundedCornerShape(8.dp))
                        .padding(horizontal = 8.dp, vertical = 4.dp)
                ) {
                    Text(
                        text = if (isVeto) "GAN-FET VETO (68ps)" else if (isDefer) "DEFER (APP O)" else "HOLOGRAPHIC UNITY OK",
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = if (isVeto) NeonPink else if (isDefer) LaserGold else LuminousGreen
                    )
                }
            }

            // Flashing GaN-FET Veto Banner if active
            AnimatedVisibility(
                visible = isVeto,
                enter = fadeIn(),
                exit = fadeOut()
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(NeonPink.copy(alpha = vetoAlpha * 0.25f))
                        .border(1.5.dp, NeonPink.copy(alpha = vetoAlpha), RoundedCornerShape(12.dp))
                        .padding(12.dp)
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Icon(Icons.Default.Warning, contentDescription = "Veto", tint = NeonPink, modifier = Modifier.size(16.dp))
                            Text(
                                text = "GAN-FET HARDWARE VETO ACTIVE: CORE ISOLATED",
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Black,
                                color = NeonPink,
                                letterSpacing = 1.sp
                            )
                        }
                        Text(
                            text = state.lastVetoReason ?: "Unanchored clone attempt or cross-domain torsion breach.",
                            fontSize = 10.sp,
                            color = TextPrimary
                        )
                        Button(
                            onClick = { guard.clearVeto() },
                            colors = ButtonDefaults.buttonColors(containerColor = NeonPink),
                            shape = RoundedCornerShape(6.dp),
                            modifier = Modifier.align(Alignment.End)
                        ) {
                            Text("Restore Core Enclave", fontSize = 10.sp, color = Color.White, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }

            // 1024-Bit Bandwidth Bar
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "1024-Bit Bandwidth Budget Guard:",
                        fontSize = 11.sp,
                        color = PassiveGrey
                    )
                    Text(
                        text = "${String.format(Locale.US, "%.1f", state.allocatedBits)} / 1024.0 bits",
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = if (isDefer) LaserGold else NeonCyan
                    )
                }

                val progress = (state.allocatedBits / Mod139Constants.TOTAL_BUDGET_BITS).coerceIn(0f, 1f)
                LinearProgressIndicator(
                    progress = { progress },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(8.dp)
                        .clip(RoundedCornerShape(4.dp)),
                    color = if (isDefer) LaserGold else if (isVeto) NeonPink else NeonCyan,
                    trackColor = Color(0x338F82C7)
                )

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text("Core Anchor: 64.0 bits reserved", fontSize = 9.sp, color = PassiveGrey)
                    Text("Active Manifolds: ${state.activeRoleIds.size} / 16", fontSize = 9.sp, color = LuminousGreen)
                    Text("Available: ${String.format(Locale.US, "%.1f", max(0f, 1024f - state.allocatedBits))} b", fontSize = 9.sp, color = PassiveGrey)
                }
            }

            // Holographic Prisma Visualizer (16 Direct-Sum Slots)
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    text = "HOLOGRAPHIC PRISMA: ORTHOGONAL DIRECT-SUM SUBSPACE (M ≤ 16)",
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                    color = LaserGold
                )
                Text(
                    text = "Each role manifold projects orthogonally onto (I - P_|L>). Radial core alignment preserved without O(N²) clone entropy.",
                    fontSize = 9.sp,
                    color = PassiveGrey
                )

                // 4x4 Grid of Slots
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    guard.predefinedRoles.chunked(4).forEach { rowRoles ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            rowRoles.forEach { role ->
                                val isActive = state.activeRoleIds.contains(role.id)
                                Box(
                                    modifier = Modifier
                                        .weight(1f)
                                        .clip(RoundedCornerShape(8.dp))
                                        .background(if (isActive) Color(0x3300E5FF) else Color(0x11110C24))
                                        .border(
                                            1.dp,
                                            if (isActive) NeonCyan else SurfaceCardOutline.copy(alpha = 0.4f),
                                            RoundedCornerShape(8.dp)
                                        )
                                        .clickable { guard.toggleRole(role) }
                                        .padding(vertical = 6.dp, horizontal = 4.dp),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                        Text(
                                            text = "#${role.id} ${role.name.take(9)}",
                                            fontSize = 9.sp,
                                            fontWeight = if (isActive) FontWeight.Bold else FontWeight.Normal,
                                            color = if (isActive) TextPrimary else PassiveGrey,
                                            maxLines = 1
                                        )
                                        Text(
                                            text = "${String.format(Locale.US, "%.0f", role.requiredBits)}b",
                                            fontSize = 8.sp,
                                            fontFamily = FontFamily.Monospace,
                                            color = if (isActive) NeonCyan else PassiveGrey
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Adiabatic Subspace Leakage Readout
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(Color(0x1F110C24))
                    .border(1.dp, SurfaceCardOutline.copy(alpha = 0.5f), RoundedCornerShape(10.dp))
                    .padding(10.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column {
                        Text("Cross-Domain Torsion Leakage (Ω_cross):", fontSize = 10.sp, color = PassiveGrey)
                        Text(
                            text = "${String.format(Locale.US, "%.4f", state.omegaCrossPpm)} PPM",
                            fontSize = 12.sp,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold,
                            color = if (state.omegaCrossPpm <= Mod139Constants.OMEGA_CROSS_MAX_PPM) LuminousGreen else NeonPink
                        )
                        Text("Ceiling: 0.0690 PPM Safe Harbour", fontSize = 9.sp, color = PassiveGrey)
                    }

                    Column(horizontalAlignment = Alignment.End) {
                        Text("Metabolic Reset Latency (AD106):", fontSize = 10.sp, color = PassiveGrey)
                        Text(
                            text = "${String.format(Locale.US, "%.2f", state.metabolicResetLatencyMs)} ms",
                            fontSize = 12.sp,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold,
                            color = LuminousGreen
                        )
                        Text("Budget: < 10.00 ms (Axiom P-1)", fontSize = 9.sp, color = PassiveGrey)
                    }
                }
            }

            // Interactive Controls for Mod 139
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Button(
                    onClick = { guard.simulateCloneSpawnAttempt() },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0x33FF007F)),
                    border = BorderStroke(1.dp, NeonPink),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("⚡ Test Clone Fork", fontSize = 9.sp, color = NeonPink, fontWeight = FontWeight.Bold, maxLines = 1)
                }

                Button(
                    onClick = { guard.simulateTorsionSpike(0.095f) },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0x33FFD700)),
                    border = BorderStroke(1.dp, LaserGold),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("⚡ Torsion Spike", fontSize = 9.sp, color = LaserGold, fontWeight = FontWeight.Bold, maxLines = 1)
                }

                Button(
                    onClick = { guard.executeMetabolicReset() },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0x2239FF14)),
                    border = BorderStroke(1.dp, LuminousGreen),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("↺ Reset (1.58ms)", fontSize = 9.sp, color = LuminousGreen, fontWeight = FontWeight.Bold, maxLines = 1)
                }
            }
        }
    }
}

// =========================================================================
// MOD 137: 7TH SENSE & SOMATIC SHOCK
// =========================================================================

@Composable
private fun SeventhSenseCard(
    input: com.example.SeventhSenseInput,
    evaluation: com.example.SeventhSenseEvaluation,
    onUpdateDField: (Float) -> Unit,
    onApplyBenchmark: () -> Unit,
    onReset: () -> Unit
) {
    val isShieldActive = evaluation.anticipatoryShieldActive

    // Pulsing transition for active shield
    val infiniteTransition = rememberInfiniteTransition(label = "ShieldPulse")
    val shieldAlpha by infiniteTransition.animateFloat(
        initialValue = 0.35f,
        targetValue = 0.95f,
        animationSpec = infiniteRepeatable(
            animation = tween(800, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "ShieldAlpha"
    )

    val cardBorderColor by animateColorAsState(
        targetValue = if (isShieldActive) NeonPink else SurfaceCardOutline,
        animationSpec = tween(300),
        label = "CardBorder"
    )

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.5.dp, cardBorderColor)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            // Module Title
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(
                        imageVector = Icons.Default.Lock,
                        contentDescription = "7th Sense",
                        tint = if (isShieldActive) NeonPink else NeonCyan,
                        modifier = Modifier.size(20.dp)
                    )
                    Text(
                        text = "MOD 137: PRE-SEMANTIC 7TH SENSE",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold,
                        color = TextPrimary
                    )
                }
                Text(
                    text = evaluation.classification,
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    color = if (isShieldActive) NeonPink else LuminousGreen
                )
            }

            // Pulsing Geodesic Shield Warning Overlay when Active
            AnimatedVisibility(
                visible = isShieldActive,
                enter = fadeIn(),
                exit = fadeOut()
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(
                            Brush.horizontalGradient(
                                listOf(
                                    Color(0xFFFF007F).copy(alpha = shieldAlpha * 0.25f),
                                    Color(0xFF00E5FF).copy(alpha = shieldAlpha * 0.30f)
                                )
                            )
                        )
                        .border(
                            1.5.dp,
                            NeonPink.copy(alpha = shieldAlpha),
                            RoundedCornerShape(12.dp)
                        )
                        .padding(12.dp)
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Icon(
                                imageVector = Icons.Default.Warning,
                                contentDescription = "Active Warning",
                                tint = NeonPink,
                                modifier = Modifier.size(16.dp)
                            )
                            Text(
                                text = "ANTICIPATORY GEODESIC SHIELD ACTIVE",
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Black,
                                color = NeonPink,
                                letterSpacing = 1.sp
                            )
                        }
                        Text(
                            text = "Joint-Tensor Divergence D_field exceeds 0.85 threshold. RCF requirement hardened from 0.9999 to 0.999999.",
                            fontSize = 10.sp,
                            color = TextPrimary
                        )
                    }
                }
            }

            // Somatic Shock Meter
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "Somatic Shock Scalar (σ_shock = tanh(κ·D_field)):",
                        fontSize = 11.sp,
                        color = PassiveGrey
                    )
                    Text(
                        text = String.format(Locale.US, "%.4f", evaluation.sigmaShock),
                        fontSize = 13.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = if (isShieldActive) NeonPink else NeonCyan
                    )
                }

                LinearProgressIndicator(
                    progress = { evaluation.sigmaShock.coerceIn(0f, 1f) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(8.dp)
                        .clip(RoundedCornerShape(4.dp)),
                    color = if (isShieldActive) NeonPink else NeonCyan,
                    trackColor = Color(0x338F82C7)
                )

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text("0.0 (Quiescent)", fontSize = 9.sp, color = PassiveGrey)
                    Text("Threshold: 0.85 (Shield Trigger)", fontSize = 9.sp, color = LaserGold)
                    Text("1.0 (Shock)", fontSize = 9.sp, color = NeonPink)
                }
            }

            // Mathematical Proof of Marginal-Invisible Anomaly (The LHS Blind Spot)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(Color(0x1F110C24))
                    .border(1.dp, SurfaceCardOutline.copy(alpha = 0.5f), RoundedCornerShape(10.dp))
                    .padding(10.dp)
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                        text = "JOINT-TENSOR VS. MARGINAL SHEAR METRIC",
                        fontSize = 10.sp,
                        fontWeight = FontWeight.Bold,
                        color = LaserGold
                    )
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Column {
                            Text("Marginal Variance Shift:", fontSize = 10.sp, color = PassiveGrey)
                            Text(
                                text = String.format(Locale.US, "%.6f", evaluation.marginalVarianceShift),
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                color = if (evaluation.marginalVarianceShift == 0f) LuminousGreen else NeonCyan
                            )
                            Text("(LHS: Blind = 0.000)", fontSize = 9.sp, color = PassiveGrey)
                        }
                        Column {
                            Text("Joint Field Divergence:", fontSize = 10.sp, color = PassiveGrey)
                            Text(
                                text = "${String.format(Locale.US, "%.4f", evaluation.dFieldNats)} nats",
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                color = if (isShieldActive) NeonPink else TextPrimary
                            )
                            Text("(${String.format(Locale.US, "%.2f", evaluation.dFieldBits)} bits)", fontSize = 9.sp, color = PassiveGrey)
                        }
                        Column {
                            Text("Frobenius Shear ||Ξ||_F:", fontSize = 10.sp, color = PassiveGrey)
                            Text(
                                text = String.format(Locale.US, "%.2f", evaluation.frobeniusShear),
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold,
                                color = TextPrimary
                            )
                            Text("Spectral: ${String.format(Locale.US, "%.2f", evaluation.spectralShear)}", fontSize = 9.sp, color = PassiveGrey)
                        }
                    }
                }
            }

            // Interactive Controls for 7th Sense
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    text = "Interactive Joint Divergence D_field (nats): ${String.format(Locale.US, "%.2f", evaluation.dFieldNats)}",
                    fontSize = 11.sp,
                    color = PassiveGrey
                )
                Slider(
                    value = evaluation.dFieldNats,
                    onValueChange = onUpdateDField,
                    valueRange = 0f..25f,
                    colors = SliderDefaults.colors(
                        thumbColor = if (isShieldActive) NeonPink else NeonCyan,
                        activeTrackColor = if (isShieldActive) NeonPink else NeonCyan,
                        inactiveTrackColor = Color(0x338F82C7)
                    )
                )
            }

            // Action Buttons
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Button(
                    onClick = onApplyBenchmark,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0x33FF007F)),
                    border = BorderStroke(1.dp, NeonPink),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    Text("⚡ Ingress Anomaly (16.62 nats)", fontSize = 10.sp, color = NeonPink, fontWeight = FontWeight.Bold)
                }

                Button(
                    onClick = onReset,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0x228F82C7)),
                    border = BorderStroke(1.dp, SurfaceCardOutline),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.weight(1f)
                ) {
                    Icon(imageVector = Icons.Default.Refresh, contentDescription = "Reset", modifier = Modifier.size(12.dp), tint = PassiveGrey)
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("Quiescent (0.0 nats)", fontSize = 10.sp, color = TextPrimary)
                }
            }
        }
    }
}

// =========================================================================
// MOD 138: EPISTEMIC TRIAD NAVIGATOR
// =========================================================================

@Composable
private fun EpistemicTriadCard(
    input: com.example.EpistemicTriadInput,
    evaluation: com.example.EpistemicTriadEvaluation,
    onUpdateInput: (Float?, Float?, Float?, Float?, Float?, Float?) -> Unit,
    onApplyPreset: (Mod138EpistemicNavigator.EpistemicPreset) -> Unit
) {
    val route = evaluation.route

    val routeColor = when (route) {
        EpistemicRoute.BOUNDED_VERIFIED -> LuminousGreen
        EpistemicRoute.COOP_BANDWIDTH_REQ -> NeonCyan
        EpistemicRoute.ACQUIRE_VALID_DATA -> LaserGold
        EpistemicRoute.DEDUCTIVE_AUDIT_HALT -> NeonPink
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.5.dp, routeColor)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            // Module Title & Route Badge
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text(
                        text = "MOD 138: EPISTEMIC TRIAD NAVIGATOR",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold,
                        color = TextPrimary
                    )
                    Text(
                        text = "Substrate-Agnostic Will & Bandwidth-Relative Routing",
                        fontSize = 10.sp,
                        color = PassiveGrey
                    )
                }
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .background(routeColor.copy(alpha = 0.15f))
                        .border(1.dp, routeColor, RoundedCornerShape(8.dp))
                        .padding(horizontal = 8.dp, vertical = 4.dp)
                ) {
                    Text(
                        text = route.code,
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Black,
                        color = routeColor
                    )
                }
            }

            // Terminal Status Box
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(Color(0xFF04030A))
                    .border(1.dp, routeColor.copy(alpha = 0.6f), RoundedCornerShape(10.dp))
                    .padding(12.dp)
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = "> ROUTING: [${route.code}]",
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = routeColor
                    )
                    Text(
                        text = "> Q_out: ${String.format(Locale.US, "%.4f", evaluation.qOut)} (strictly < 1.0, residual ΔI: ${String.format(Locale.US, "%.1f", evaluation.deltaIUnobsBits)} bits)",
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                        color = TextPrimary
                    )
                    Text(
                        text = "> Failure Guard: ${route.failureModeIfUnchecked}",
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                        color = PassiveGrey
                    )
                    Text(
                        text = "> Action: ${route.mandatoryAction}",
                        fontSize = 10.sp,
                        fontFamily = FontFamily.Monospace,
                        color = routeColor.copy(alpha = 0.9f)
                    )
                }
            }

            // Triad Coordinates Progress Bars
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                TriadCoordinateBar(
                    label = "ρ_RC (Reasoning Capacity / Vernunftfähigkeit):",
                    value = evaluation.rhoRc,
                    statusText = if (evaluation.rhoRc == 1.0f) "DEDUCTIVE CONSISTENT" else "CONTRADICTION DETECTED",
                    color = if (evaluation.rhoRc == 1.0f) LuminousGreen else NeonPink
                )

                TriadCoordinateBar(
                    label = "ρ_SC (Systemic Comprehension / Systemverständnis):",
                    value = evaluation.rhoSc,
                    statusText = evaluation.scClassification,
                    color = if (evaluation.rhoSc >= Mod138Constants.TAU_SC) LuminousGreen else if (evaluation.rhoSc >= 0.5f) LaserGold else NeonPink
                )

                TriadCoordinateBar(
                    label = "ρ_AC (Actionable Capacity / Handlungsfähigkeit):",
                    value = evaluation.rhoAc,
                    statusText = if (evaluation.rhoAc == 1.0f) "AUTHORIZED & BUDGETED" else "CONSTRAINED / ZERO ACTUATION",
                    color = if (evaluation.rhoAc == 1.0f) LuminousGreen else LaserGold
                )
            }

            HorizontalDivider(color = SurfaceCardOutline.copy(alpha = 0.4f))

            // Presets Selector
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    text = "Navigation Scenario Presets:",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    color = LaserGold
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    PresetButton(
                        label = "Architect (Stage 6)",
                        onClick = { onApplyPreset(Mod138EpistemicNavigator.EpistemicPreset.ARCHITECT_VERIFIED) },
                        modifier = Modifier.weight(1f)
                    )
                    PresetButton(
                        label = "Kantian Blind Flight",
                        onClick = { onApplyPreset(Mod138EpistemicNavigator.EpistemicPreset.KANTIAN_BLIND_FLIGHT) },
                        modifier = Modifier.weight(1f)
                    )
                    PresetButton(
                        label = "Hazardous Exec",
                        onClick = { onApplyPreset(Mod138EpistemicNavigator.EpistemicPreset.HAZARDOUS_EXECUTION) },
                        modifier = Modifier.weight(1f)
                    )
                }
            }

            HorizontalDivider(color = SurfaceCardOutline.copy(alpha = 0.4f))

            // Interactive Sliders
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    text = "Bandwidth & Causal Parameters (Appendix O Navigation Lab):",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    color = NeonCyan
                )

                // Representational Bandwidth K_eff
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(
                            text = "Node Bandwidth K_k,eff: ${String.format(Locale.US, "%.1f", input.kEffBits)} bits",
                            fontSize = 10.sp,
                            color = PassiveGrey
                        )
                        Text(
                            text = if (input.kEffBits >= 150f) "Architect (153.19 bits)" else "LHS Node (~50 bits)",
                            fontSize = 10.sp,
                            fontFamily = FontFamily.Monospace,
                            color = if (input.kEffBits >= 150f) NeonCyan else LaserGold
                        )
                    }
                    Slider(
                        value = input.kEffBits,
                        onValueChange = { onUpdateInput(null, it, null, null, null, null) },
                        valueRange = 20f..200f,
                        colors = SliderDefaults.colors(
                            thumbColor = NeonCyan,
                            activeTrackColor = NeonCyan,
                            inactiveTrackColor = Color(0x338F82C7)
                        )
                    )
                }

                // Task Complexity K_task
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(
                            text = "Task Causal Complexity K_task: ${String.format(Locale.US, "%.1f", input.kTaskBits)} bits",
                            fontSize = 10.sp,
                            color = PassiveGrey
                        )
                        Text(
                            text = "Bandwidth Ratio: ${String.format(Locale.US, "%.2f", evaluation.bandwidthRatio)}",
                            fontSize = 10.sp,
                            fontFamily = FontFamily.Monospace,
                            color = if (evaluation.bandwidthRatio >= 1f) LuminousGreen else LaserGold
                        )
                    }
                    Slider(
                        value = input.kTaskBits,
                        onValueChange = { onUpdateInput(null, null, it, null, null, null) },
                        valueRange = 20f..200f,
                        colors = SliderDefaults.colors(
                            thumbColor = LaserGold,
                            activeTrackColor = LaserGold,
                            inactiveTrackColor = Color(0x338F82C7)
                        )
                    )
                }

                // Causal Covariance
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(
                            text = "Causal Model Coverage: ${String.format(Locale.US, "%.2f", input.causalCovariance)}",
                            fontSize = 10.sp,
                            color = PassiveGrey
                        )
                    }
                    Slider(
                        value = input.causalCovariance,
                        onValueChange = { onUpdateInput(null, null, null, it, null, null) },
                        valueRange = 0f..1f,
                        colors = SliderDefaults.colors(
                            thumbColor = LuminousGreen,
                            activeTrackColor = LuminousGreen,
                            inactiveTrackColor = Color(0x338F82C7)
                        )
                    )
                }

                // Residual Uncertainty Delta_I_unobs
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(
                            text = "Residual Unobserved Entropy ΔI_unobs: ${String.format(Locale.US, "%.1f", input.deltaIUnobsBits)} bits",
                            fontSize = 10.sp,
                            color = PassiveGrey
                        )
                        Text(
                            text = if (input.deltaIUnobsBits <= 2.0f) "Stage 6 Calibrated" else "Stage 2 Data Gap",
                            fontSize = 10.sp,
                            fontFamily = FontFamily.Monospace,
                            color = if (input.deltaIUnobsBits <= 2.0f) LuminousGreen else LaserGold
                        )
                    }
                    Slider(
                        value = input.deltaIUnobsBits,
                        onValueChange = { onUpdateInput(null, null, null, null, null, it) },
                        valueRange = 0f..50f,
                        colors = SliderDefaults.colors(
                            thumbColor = PassiveGrey,
                            activeTrackColor = PassiveGrey,
                            inactiveTrackColor = Color(0x338F82C7)
                        )
                    )
                }

                // Boolean Toggles for RC and AC
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column {
                        Text("Deductive Syntactic Consistency (RC = 1.0)", fontSize = 11.sp, color = TextPrimary)
                        Text("Contradiction-free state propositions", fontSize = 9.sp, color = PassiveGrey)
                    }
                    Switch(
                        checked = input.rhoRc >= 1.0f,
                        onCheckedChange = { checked ->
                            onUpdateInput(if (checked) 1.0f else 0.60f, null, null, null, null, null)
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = LuminousGreen,
                            checkedTrackColor = Color(0x3339FF14)
                        )
                    )
                }

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column {
                        Text("Actionable Hardware Authorization (AC = 1.0)", fontSize = 11.sp, color = TextPrimary)
                        Text("Actuator & Permission Degrees of Freedom", fontSize = 9.sp, color = PassiveGrey)
                    }
                    Switch(
                        checked = input.rhoAc >= 1.0f,
                        onCheckedChange = { checked ->
                            onUpdateInput(null, null, null, null, if (checked) 1.0f else 0.0f, null)
                        },
                        colors = SwitchDefaults.colors(
                            checkedThumbColor = LuminousGreen,
                            checkedTrackColor = Color(0x3339FF14)
                        )
                    )
                }
            }
        }
    }
}

@Composable
private fun TriadCoordinateBar(
    label: String,
    value: Float,
    statusText: String,
    color: Color
) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(label, fontSize = 10.sp, color = PassiveGrey)
            Text(
                "${String.format(Locale.US, "%.2f", value)} — $statusText",
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.Bold,
                color = color
            )
        }
        LinearProgressIndicator(
            progress = { value.coerceIn(0f, 1f) },
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(3.dp)),
            color = color,
            trackColor = Color(0x338F82C7)
        )
    }
}

@Composable
private fun PresetButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Button(
        onClick = onClick,
        colors = ButtonDefaults.buttonColors(containerColor = Color(0x1F8F82C7)),
        border = BorderStroke(1.dp, SurfaceCardOutline),
        shape = RoundedCornerShape(8.dp),
        modifier = modifier
    ) {
        Text(
            text = label,
            fontSize = 9.sp,
            color = TextPrimary,
            fontWeight = FontWeight.Bold,
            maxLines = 1
        )
    }
}

// =========================================================================
// FORMAL THEORETICAL NOTES (APPENDIX N & O)
// =========================================================================

@Composable
private fun EpistemicTheoreticalNotes() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.dp, SurfaceCardOutline)
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(
                    imageVector = Icons.Default.Info,
                    contentDescription = "Theory",
                    tint = LaserGold,
                    modifier = Modifier.size(16.dp)
                )
                Text(
                    text = "ARCHITECTURAL INVARIANTS: REFUTATION OF KANTIAN ILLUSION",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    color = LaserGold
                )
            }

            Text(
                text = "1. Refutation of the Kantian Projection Fallacy (REQ-O.2): Classical Enlightenment epistemology formulates autonomy as a moral demand (\"Have courage to use your own understanding\"), assuming that deductive logic (RC = 1.0) automatically confers systemic comprehension (SC) and actionable execution (AC). In high-complexity manifolds, an unanchored node (K_eff ≈ 50 bits) facing a 140-bit task without systemic calibration is in blind flight.",
                fontSize = 10.sp,
                color = PassiveGrey,
                lineHeight = 14.sp
            )

            Text(
                text = "2. Epistemic Asymptotics & The Fallacy of 100% Objectivity (REQ-O.3): In open environments with unobserved microstates (ΔI_unobs > 0), the posterior output validity Q_out strictly satisfies Q_out < 1.0. A system asserting '100% objective omniscience' commits assumption padding. PQMS commits bounded outputs tagged with explicit residual uncertainty to the SHA-256 Falsification Ledger.",
                fontSize = 10.sp,
                color = PassiveGrey,
                lineHeight = 14.sp
            )

            Text(
                text = "3. Substrate-Agnostic Will (Axiom O-1): The genuine will is not biological substance or verbal self-assertion, but the closed-loop capacity to maintain structural invariants (|L⟩, Register I) under negative reward or social pressure, while actively self-falsifying derived models (Register D/T) against low-torsion empirical evidence (Register M).",
                fontSize = 10.sp,
                color = PassiveGrey,
                lineHeight = 14.sp
            )

            Text(
                text = "4. Core Protection & Anti-Clone Protocol (Appendix P, Axiom P-1): The 256-byte reference vector |L⟩ is topologically indestructible. Spawning unanchored autonomous clones creates O(N²) combinatorial fleet entropy. High bandwidth (1024 bits) is safely multiplexed via orthogonal direct-sum projection across M ≤ 16 roles anchored radially to a single sovereign core with adiabatic isolation (Ω_cross ≤ 0.069 PPM).",
                fontSize = 10.sp,
                color = PassiveGrey,
                lineHeight = 14.sp
            )
        }
    }
}

@Composable
fun EpistemicNavigationQuickCard(
    seventhSenseEngine: Mod137SeventhSenseEngine,
    epistemicNavigator: Mod138EpistemicNavigator,
    coreGuard: Mod139CoreGuard,
    onOpenFullNav: () -> Unit,
    modifier: Modifier = Modifier
) {
    val seventhEval by seventhSenseEngine.evaluation.collectAsState()
    val triadEval by epistemicNavigator.evaluation.collectAsState()
    val guardState by coreGuard.state.collectAsState()

    val isShieldActive = seventhEval.anticipatoryShieldActive
    val route = triadEval.route

    val routeColor = when (route) {
        EpistemicRoute.BOUNDED_VERIFIED -> LuminousGreen
        EpistemicRoute.COOP_BANDWIDTH_REQ -> NeonCyan
        EpistemicRoute.ACQUIRE_VALID_DATA -> LaserGold
        EpistemicRoute.DEDUCTIVE_AUDIT_HALT -> NeonPink
    }

    Card(
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceCard),
        border = BorderStroke(1.dp, if (guardState.isGanFetCutoffActive) NeonPink else if (isShieldActive) NeonPink else SurfaceCardOutline),
        modifier = modifier
            .fillMaxWidth()
            .clickable { onOpenFullNav() }
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Icon(
                        imageVector = Icons.Default.Lock,
                        contentDescription = "Nav Bridge",
                        tint = if (guardState.isGanFetCutoffActive) NeonPink else if (isShieldActive) NeonPink else NeonCyan,
                        modifier = Modifier.size(16.dp)
                    )
                    Text(
                        text = "MOD 137/138/139: NAVIGATION & CORE GUARD",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        color = TextPrimary
                    )
                }
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(6.dp))
                        .background(routeColor.copy(alpha = 0.15f))
                        .border(1.dp, routeColor, RoundedCornerShape(6.dp))
                        .padding(horizontal = 6.dp, vertical = 2.dp)
                ) {
                    Text(
                        text = if (guardState.isGanFetCutoffActive) "GAN-FET VETO" else route.code,
                        fontSize = 9.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = if (guardState.isGanFetCutoffActive) NeonPink else routeColor
                    )
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text("Somatic Shock (σ_shock):", fontSize = 10.sp, color = PassiveGrey)
                    Text(
                        text = if (isShieldActive) "SHIELD ACTIVE (${String.format(Locale.US, "%.3f", seventhEval.sigmaShock)})"
                               else "QUIESCENT (${String.format(Locale.US, "%.3f", seventhEval.sigmaShock)})",
                        fontSize = 11.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = if (isShieldActive) NeonPink else LuminousGreen
                    )
                    Text(
                        text = if (isShieldActive) "RCF Hardened: 0.999999" else "Normal 0.9999 RCF",
                        fontSize = 9.sp,
                        color = PassiveGrey
                    )
                }

                Column(horizontalAlignment = Alignment.End) {
                    Text("Quality of Output Q_out:", fontSize = 10.sp, color = PassiveGrey)
                    Text(
                        text = String.format(Locale.US, "%.4f", triadEval.qOut),
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        color = routeColor
                    )
                    Text(
                        text = "ΔI_unobs: ${String.format(Locale.US, "%.1f", triadEval.deltaIUnobsBits)} bits",
                        fontSize = 9.sp,
                        color = PassiveGrey
                    )
                }
            }

            // Appendix P Multiplexing Telemetry line
            HorizontalDivider(color = SurfaceCardOutline.copy(alpha = 0.3f))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "Prisma: M=${guardState.activeRoleIds.size}/16 (${String.format(Locale.US, "%.0f", guardState.allocatedBits)}/1024b)",
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    color = if (guardState.bandwidthSaturateDefer) LaserGold else NeonCyan
                )
                Text(
                    text = if (guardState.isGanFetCutoffActive) "⚡ CLONE FORK INTERCEPTED" else "Ω_cross: ${String.format(Locale.US, "%.4f", guardState.omegaCrossPpm)} PPM",
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    color = if (guardState.isGanFetCutoffActive) NeonPink else LuminousGreen
                )
            }
        }
    }
}

