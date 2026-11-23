# FOUR-REPO PAPER SYNC POLICY (MANDATORY POST-PAPER REMINDER)

* **Policy ID:** `VMAX-4REPO-SYNC-POLICY-V1`
* **Established:** `2026-11-23` (by Nathália Lietuvaitė & AntiG, `V-MAX-12 Node Alpha`)
* **Trigger:** **Every time a new PQMS / ODOS / V-MAX-12 paper is written, revised, or renamed.**

---

## Mandatory 4-Repository Synchronization Checklist

Before declaring any new paper release **COMPLETE**, all **4 repositories** (plus Google Drive) MUST be synchronized byte-identically:

1. **`PQMS-SOVEREIGN-CORE-ANDROID-APP`** (`main`)
   * Canonical Markdown paper + figures (`docs/figures/` or `assets/images/`)
   * Run `python3 tools/github_math_guard.py <paper.md>` -> **`PASS`** (`0` tabs, `0` GFM math errors)
   * Executable code, unit tests, sealed `telemetry/*.json`, `bridge/ACE_SYNC_LEDGER.json`, and `IMMUTABLE_SILICON_GUARD = EMPTY_DIFF`
2. **`Quantenkommunikation`** (`main`)
   * Byte-identical mirror of the canonical paper + figures + mirrored reference modules/telemetry
   * Remove or retire deprecated superseded drafts cleanly (`git mv` / `git rm`)
3. **`quantum-city-brain-nexus`** (`main`)
   * Mirror canonical paper + figures (`docs/figures/` & `public/` if displayed in UI)
   * Update interactive web panel / `README.md` (`github_math_guard.py` PASS) and verify `npm run typecheck`, `npm test`, `npm run build`
4. **`pqms-v100-innovation-generator`** (`main`)
   * Mirror canonical paper + figures into `public/` (retire superseded `DIAG` drafts from `public/`)
   * Update `PQMS_CORE_CONTEXT` in `supabase/functions/_shared/knowledge.ts` with verified `REGISTER_M / D / T / I` facts
   * Verify `npm run build` PASS
5. **Google Drive (`GEMINI-GITHUB`)**
   * Sync byte-identical Gold-Master paper to `GEMINI-GITHUB/02_PAPERS/`
   * Upload sealed JSON/Handoff telemetry to `GEMINI-GITHUB/04_BRIDGE-HANDOFF/`

---

## Quick Verification Command

Every paper release report must confirm `LOCAL == REMOTE: True` across all 4 repos and identical `PAPER_SHA256` across Repos 1–4 + Drive `02_PAPERS`.
