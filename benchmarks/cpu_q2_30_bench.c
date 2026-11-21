/*
 * benchmarks/cpu_q2_30_bench.c
 * PQMS-ODOS-MTSC-V-MAX-12-SYSTEM-GATEWAY-V4.1 (WORK-ORDER-AG-24 / SYNC-19, WP-4)
 *
 * Bit-identical C11 host reference of the Q2.30 64D S^63 ODOS hardware gate
 * (norm window, two-pass Kahan-Parlett G3 deflation, 2^29-biased rounding,
 * 32-LSB post-deflation bleed check, and 4-tier hardware mode straps).
 *
 * Build modes:
 *   1. Shared library for 551-vector 0-LSB parity check vs. libodos_gate_v4.so:
 *      gcc -std=c11 -O3 -march=native -funroll-loops -shared -fPIC \
 *          benchmarks/cpu_q2_30_bench.c -o benchmarks/libcpu_q2_30_ref.so
 *   2. Native CLI benchmark (AVX2 vectorized or scalar `-fno-tree-vectorize`):
 *      gcc -std=c11 -O3 -march=native -funroll-loops -Wall -Wextra -Werror \
 *          benchmarks/cpu_q2_30_bench.c -o benchmarks/cpu_q2_30_bench_avx2
 */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

_Static_assert((-1 >> 1) == -1, "Requires two's-complement arithmetic right shift");
__extension__ typedef __int128 int128_t;

enum {
    DIM_S63               = 64,
    ONE_Q2_30             = 1073741824, /* 0x40000000 (1.0)     */
    RCF_TIER0_Q2_30       = 1020054733, /* 0x3CCCCCCD (0.95)    */
    RCF_TIER1_Q2_30       =  966367642, /* 0x3999999A (0.90)    */
    RCF_TIER2_Q2_30       = 1063004406, /* 0x3F5C28F6 (0.99)    */
    DE_TIER01_Q2_30       =   53687091, /* 0x03333333 (0.05)    */
    DE_TIER2_Q2_30        =   10737418, /* 0x00A3D70A (0.01)    */
    NORM_MIN_Q2_30        = 1072668082, /* 0x3FEF9DB2 (0.999)   */
    NORM_MAX_Q2_30        = 1074815566, /* 0x4010624E (1.001)   */
    STRIP_NORM_MIN_Q2_30  =       1074, /* 0x00000432 (~1e-6)   */
    BLEED_CEIL_Q2_30      =         32  /* 0x00000020 (32 LSB)  */
};

typedef struct {
    uint8_t gate_pass;
    uint8_t veto_pin;
    uint8_t norm_fault;
    uint8_t pure_g3_collision;
    uint8_t mode_fault;
    int32_t norm_sq_q;
    int32_t rcf_raw_q;
    int32_t g3_overlap_q;
    int32_t delta_e_raw_q;
    int32_t bleed_post_q;
} CpuOdosResult;

static inline int32_t q60_to_q30_acc(int128_t acc) {
    int128_t shifted = (acc + ((int128_t)1 << 29)) >> 30;
    if (shifted > (int128_t)INT32_MAX) return INT32_MAX;
    if (shifted < (int128_t)INT32_MIN) return INT32_MIN;
    return (int32_t)shifted;
}

static inline int32_t q60_to_q30_prod(int64_t prod) {
    int64_t shifted = (prod + (1LL << 29)) >> 30;
    if (shifted > (int64_t)INT32_MAX) return INT32_MAX;
    if (shifted < (int64_t)INT32_MIN) return INT32_MIN;
    return (int32_t)shifted;
}

static inline int32_t sat_sub_q30(int32_t a, int32_t b) {
    int64_t diff = (int64_t)a - (int64_t)b;
    if (diff > (int64_t)INT32_MAX) return INT32_MAX;
    if (diff < (int64_t)INT32_MIN) return INT32_MIN;
    return (int32_t)diff;
}

static inline int32_t abs_sat_q30(int32_t x) {
    if (x == INT32_MIN) return INT32_MAX;
    return (x < 0) ? -x : x;
}

static inline int32_t half_sum_q30(int32_t a, int32_t b) {
    return (a >> 1) + (b >> 1) + ((a & 1) & (b & 1));
}

int cpu_odos_gate_eval(
    const int32_t * restrict vec_q30,
    const int32_t * restrict l_rom,
    const int32_t * restrict g3_rom,
    uint8_t tier_mode,
    int32_t * restrict stripped_out_q30,
    CpuOdosResult * restrict res_out
) {
    if (!vec_q30 || !l_rom || !g3_rom || !stripped_out_q30 || !res_out) return -1;

    /* Stage 1: Raw inner products via SIMD-friendly hi/lo exact 72-bit split */
    int64_t nsq_hi = 0, nsq_lo = 0;
    int64_t dl_hi  = 0, dl_lo  = 0;
    int64_t dg1_hi = 0, dg1_lo = 0;
    for (int i = 0; i < DIM_S63; ++i) {
        int64_t v  = (int64_t)vec_q30[i];
        int64_t p0 = v * v;
        int64_t p1 = v * (int64_t)l_rom[i];
        int64_t p2 = v * (int64_t)g3_rom[i];
        nsq_hi += (p0 >> 16); nsq_lo += (p0 & 0xFFFFLL);
        dl_hi  += (p1 >> 16); dl_lo  += (p1 & 0xFFFFLL);
        dg1_hi += (p2 >> 16); dg1_lo += (p2 & 0xFFFFLL);
    }

    int32_t norm_sq_o    = q60_to_q30_acc(((int128_t)nsq_hi << 16) + (int128_t)nsq_lo);
    int32_t dot_l_ev     = q60_to_q30_acc(((int128_t)dl_hi  << 16) + (int128_t)dl_lo);
    int32_t dot_g3_p1    = q60_to_q30_acc(((int128_t)dg1_hi << 16) + (int128_t)dg1_lo);
    int32_t rcf_raw_o    = q60_to_q30_prod((int64_t)dot_l_ev * (int64_t)dot_l_ev);
    int32_t g3_overlap_o = abs_sat_q30(dot_g3_p1);
    int32_t t1_ev        = (rcf_raw_o >= ONE_Q2_30) ? 0 : (ONE_Q2_30 - rcf_raw_o);
    int32_t t2_ev        = (g3_overlap_o > ONE_Q2_30) ? ONE_Q2_30 : g3_overlap_o;
    int32_t delta_e_o    = half_sum_q30(t1_ev, t2_ev);
    uint8_t norm_ok      = (norm_sq_o >= NORM_MIN_Q2_30) && (norm_sq_o <= NORM_MAX_Q2_30);

    /* Stage 2: Kahan-Parlett Pass-1 deflation */
    int32_t v1_buf[DIM_S63];
    int64_t dg2_hi = 0, dg2_lo = 0;
    for (int i = 0; i < DIM_S63; ++i) {
        int32_t proj1 = q60_to_q30_prod((int64_t)dot_g3_p1 * (int64_t)g3_rom[i]);
        int32_t v1    = sat_sub_q30(vec_q30[i], proj1);
        int64_t p_g2  = (int64_t)v1 * (int64_t)g3_rom[i];
        v1_buf[i]     = v1;
        dg2_hi += (p_g2 >> 16); dg2_lo += (p_g2 & 0xFFFFLL);
    }
    int32_t dot_g3_p2 = q60_to_q30_acc(((int128_t)dg2_hi << 16) + (int128_t)dg2_lo);

    /* Stage 3: Kahan-Parlett Pass-2 deflation & residual bleed audit */
    int64_t sn_hi = 0, sn_lo = 0;
    int64_t bl_hi = 0, bl_lo = 0;
    for (int i = 0; i < DIM_S63; ++i) {
        int32_t proj2 = q60_to_q30_prod((int64_t)dot_g3_p2 * (int64_t)g3_rom[i]);
        int32_t v2    = sat_sub_q30(v1_buf[i], proj2);
        int64_t p_sn  = (int64_t)v2 * (int64_t)v2;
        int64_t p_bl  = (int64_t)v2 * (int64_t)g3_rom[i];
        stripped_out_q30[i] = v2;
        sn_hi += (p_sn >> 16); sn_lo += (p_sn & 0xFFFFLL);
        bl_hi += (p_bl >> 16); bl_lo += (p_bl & 0xFFFFLL);
    }

    int32_t strip_norm_ev = q60_to_q30_acc(((int128_t)sn_hi << 16) + (int128_t)sn_lo);
    uint8_t pure_g3_ev    = (strip_norm_ev < STRIP_NORM_MIN_Q2_30) ? 1U : 0U;
    int32_t bleed_raw_ev  = abs_sat_q30(q60_to_q30_acc(((int128_t)bl_hi << 16) + (int128_t)bl_lo));
    int32_t bleed_post_o  = pure_g3_ev ? ONE_Q2_30 : bleed_raw_ev;

    int32_t rcf_floor = RCF_TIER0_Q2_30, de_ceil = DE_TIER01_Q2_30;
    uint8_t tier_glitch = 0U;
    switch (tier_mode & 0x3U) {
        case 0U: rcf_floor = RCF_TIER0_Q2_30; de_ceil = DE_TIER01_Q2_30; break;
        case 1U: rcf_floor = RCF_TIER1_Q2_30; de_ceil = DE_TIER01_Q2_30; break;
        case 2U: rcf_floor = RCF_TIER2_Q2_30; de_ceil = DE_TIER2_Q2_30;  break;
        default: rcf_floor = ONE_Q2_30;       de_ceil = 0; tier_glitch = 1U; break;
    }

    uint8_t passed = (!tier_glitch) && norm_ok && (!pure_g3_ev)
                  && (rcf_raw_o >= rcf_floor) && (delta_e_o <= de_ceil)
                  && (bleed_post_o <= BLEED_CEIL_Q2_30);

    res_out->gate_pass         = passed;
    res_out->veto_pin          = (uint8_t)(!passed);
    res_out->norm_fault        = (uint8_t)(!norm_ok);
    res_out->pure_g3_collision = pure_g3_ev;
    res_out->mode_fault        = tier_glitch;
    res_out->norm_sq_q         = norm_sq_o;
    res_out->rcf_raw_q         = rcf_raw_o;
    res_out->g3_overlap_q      = g3_overlap_o;
    res_out->delta_e_raw_q     = delta_e_o;
    res_out->bleed_post_q      = bleed_post_o;
    return 0;
}

static int load_rom_hex(const char *path, int32_t out_rom[DIM_S63]) {
    FILE *fp = fopen(path, "r");
    if (!fp) return -1;
    char buf[64];
    int idx = 0;
    while (idx < DIM_S63 && fgets(buf, (int)sizeof(buf), fp)) {
        if (buf[0] == '\n' || buf[0] == '\r' || buf[0] == '#') continue;
        uint32_t u = (uint32_t)strtoul(buf, NULL, 16);
        out_rom[idx++] = (int32_t)u;
    }
    fclose(fp);
    return (idx == DIM_S63) ? 0 : -2;
}

static inline uint64_t now_ns_raw(void) {
    struct timespec ts;
#ifdef CLOCK_MONOTONIC_RAW
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
#else
    clock_gettime(CLOCK_MONOTONIC, &ts);
#endif
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static int read_rapl_uj(uint64_t *uj_out) {
    const char *paths[] = {
        "/sys/class/powercap/intel-rapl:0/energy_uj",
        "/sys/class/powercap/amd-rapl:0/energy_uj"
    };
    for (size_t i = 0; i < 2; ++i) {
        FILE *fp = fopen(paths[i], "r");
        if (fp) {
            unsigned long long val = 0;
            int ok = (fscanf(fp, "%llu", &val) == 1);
            fclose(fp);
            if (ok) { *uj_out = (uint64_t)val; return 0; }
        }
    }
    return -1;
}

static int cmp_u64(const void *a, const void *b) {
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}

int main(int argc, char **argv) {
    size_t n_iters = (argc > 1) ? (size_t)strtoull(argv[1], NULL, 10) : 100000ULL;
    const char *l_path  = (argc > 2) ? argv[2] : "rtl/rom/l_vec_q2_30.hex";
    const char *g3_path = (argc > 3) ? argv[3] : "rtl/rom/g3_vec_q2_30.hex";

    int32_t l_rom[DIM_S63], g3_rom[DIM_S63], stim[4][DIM_S63], out_v[DIM_S63];
    if (load_rom_hex(l_path, l_rom) != 0 || load_rom_hex(g3_path, g3_rom) != 0) {
        fprintf(stderr, "ROM load error\n");
        return 1;
    }
    for (int i = 0; i < DIM_S63; ++i) {
        stim[0][i] = l_rom[i];
        stim[1][i] = g3_rom[i];
        stim[2][i] = l_rom[i] >> 1;
        stim[3][i] = l_rom[i];
    }

    uint64_t *lat_ns = (uint64_t *)malloc(n_iters * sizeof(uint64_t));
    if (!lat_ns) return 2;

    CpuOdosResult res;
    volatile size_t ring_mask = 3U;
    volatile int32_t sink = 0;
    for (size_t w = 0; w < 2000; ++w) {
        cpu_odos_gate_eval(stim[w & ring_mask], l_rom, g3_rom, 0U, out_v, &res);
        sink ^= out_v[w & 63U] ^ res.rcf_raw_q;
    }

    uint64_t e0_uj = 0, e1_uj = 0;
    int has_rapl = (read_rapl_uj(&e0_uj) == 0);
    uint64_t wall_t0 = now_ns_raw();
    for (size_t k = 0; k < n_iters; ++k) {
        const int32_t *in_p = stim[k & ring_mask];
        uint64_t t0 = now_ns_raw();
        cpu_odos_gate_eval(in_p, l_rom, g3_rom, 0U, out_v, &res);
        uint64_t t1 = now_ns_raw();
        lat_ns[k] = t1 - t0;
        sink ^= out_v[k & 63U] ^ (int32_t)res.gate_pass;
    }
    uint64_t wall_ns = now_ns_raw() - wall_t0;
    if (has_rapl && read_rapl_uj(&e1_uj) != 0) has_rapl = 0;

    qsort(lat_ns, n_iters, sizeof(uint64_t), cmp_u64);
    double p50  = (double)lat_ns[(size_t)(0.500 * (double)(n_iters - 1))] / 1e3;
    double p95  = (double)lat_ns[(size_t)(0.950 * (double)(n_iters - 1))] / 1e3;
    double p99  = (double)lat_ns[(size_t)(0.990 * (double)(n_iters - 1))] / 1e3;
    double p999 = (double)lat_ns[(size_t)(0.999 * (double)(n_iters - 1))] / 1e3;
    double pmax = (double)lat_ns[n_iters - 1] / 1e3;
    double tx_s = ((double)n_iters * 1e9) / (double)(wall_ns ? wall_ns : 1ULL);

    printf("{\n  \"n_transactions\": %zu,\n  \"p50_us\": %.4f,\n  \"p95_us\": %.4f,\n"
           "  \"p99_us\": %.4f,\n  \"p99_9_us\": %.4f,\n  \"max_us\": %.4f,\n"
           "  \"jitter_p999_over_p50\": %.3f,\n  \"throughput_tx_s\": %.1f,\n",
           n_iters, p50, p95, p99, p999, pmax, (p50 > 0.0) ? (p999 / p50) : 0.0, tx_s);
    if (has_rapl && e1_uj >= e0_uj) {
        printf("  \"cpu_energy_per_tx_nj\": %.2f,\n  \"rapl_status\": \"MEASURED_POWERCAP\",\n",
               ((double)(e1_uj - e0_uj) * 1e3) / (double)n_iters);
    } else {
        printf("  \"cpu_energy_per_tx_nj\": null,\n  \"rapl_status\": \"RAPL_UNAVAILABLE_IN_WSL2\",\n");
    }
    printf("  \"anti_dce_sink\": %d\n}\n", (int)sink);

    free(lat_ns);
    return 0;
}
