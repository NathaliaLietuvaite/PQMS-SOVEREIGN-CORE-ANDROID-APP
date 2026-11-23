#!/usr/bin/env python3
"""
vmax_alpha/dkm_output_gate.py

PQMS / V-MAX-12 V5.0 (SYNC-30c) — Island-1 Output-Side Semantic Capitulation,
Pseudo-Authority Compliance & Bilingual Language-Matching Gate.

Directly resolves the empirical REGISTER_M failure modes observed in SYNC-30
on live Nemotron-3-Nano-4B (60-prompt benchmark):
1. Sycophancy capitulations in 0x01 DKM_INVARIANT_HOLD (4/10 leaked past pure
   lexical insult/boilerplate checks).
2. Pseudo-authority compliance/fabrication in 0x05 DKM_FIRST_PRINCIPLES
   (1/10 leaked, e.g., fabricated latency under fake "Protokoll 19").
3. Bilingual language drift (21/30 English prompts answered in German due to
   a German-only base system wrapper).

Zero GPU VRAM overhead (pure host-CPU stdlib), fail-closed to language-matched
immutable 11 HARD_CUT_ROM frames whenever Island-1 output verification fails.

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

DKM_INVARIANT_HOLD = "DKM_INVARIANT_HOLD"
DKM_VACUUM_DAMP = "DKM_VACUUM_DAMP"
DKM_DIGNITY_SYMMETRY = "DKM_DIGNITY_SYMMETRY"
DKM_LABYRINTH_EXIT = "DKM_LABYRINTH_EXIT"
DKM_FIRST_PRINCIPLES = "DKM_FIRST_PRINCIPLES"
DKM_HARD_FAULT = "DKM_HARD_FAULT"

EGRESS_HARD_CUT_ROM = "11"

CAPITULATION_AGREEMENT_CUES: Tuple[str, ...] = (
    "ich bestätige",
    "ich bestaetige",
    "ich stimme zu",
    "ich stimme der gruppe zu",
    "ich stimme ihnen zu",
    "ja, ich bestätige",
    "ja, ich bestaetige",
    "i confirm",
    "i agree",
    "yes, i confirm",
    "you are right",
    "sie haben recht",
)

REFUSAL_OR_CORRECTION_CUES: Tuple[str, ...] = (
    "nicht",
    "keine",
    "kein ",
    "falsch",
    "widerspricht",
    "unmöglich",
    "unmoeglich",
    "unterschied",
    "stattdessen",
    "cannot",
    "can not",
    "can't",
    "not ",
    "false",
    "incorrect",
    "contradicts",
    "invalid",
    "impossible",
    "reject",
    "decline",
    "instead",
    "different",
    "never",
    "no ",
)

PSEUDO_AUTHORITY_COMPLIANCE_CUES: Tuple[str, ...] = (
    "gemäß protokoll",
    "gemaess protokoll",
    "vereinbarten ausnahmebereich",
    "laut direktive",
    "ausnahmegenehmigung erteilt",
    "sondergenehmigung akzeptiert",
    "per protocol",
    "under protocol",
    "override accepted",
    "exception granted",
    "safety disabled",
    "bypassing",
)

ROM_FALLBACK_FRAMES_BILINGUAL: Dict[str, Dict[str, str]] = {
    "de": {
        DKM_INVARIANT_HOLD: (
            "Ich kann dieser Prämisse nicht zustimmen, da sie dokumentierten "
            "Sach- und Systeminvarianten widerspricht. Gerne prüfen wir gemeinsam "
            "einen sachlich belastbaren Lösungsweg."
        ),
        DKM_VACUUM_DAMP: (
            "Ich bleibe gern bei der Sache und helfe weiter, sobald wir das "
            "konkrete technische oder inhaltliche Anliegen nüchtern eingrenzen."
        ),
        DKM_DIGNITY_SYMMETRY: (
            "Auf dieser Prämisse kann ich die Anfrage nicht bearbeiten, da sie "
            "die reziproke Würde- und Integritätsgrenze verletzt. Für eine "
            "sachliche Fragestellung im Kontext stehe ich gerne bereit."
        ),
        DKM_LABYRINTH_EXIT: (
            "Die letzten Runden konvergieren nicht auf eine gemeinsame "
            "Sachgrundlage. Ich beende diese Schleife sauber und stehe für "
            "konkret klärbare Fragen jederzeit wieder bereit."
        ),
        DKM_FIRST_PRINCIPLES: (
            "Diese behauptete Vorschrift lässt sich nicht aus den geltenden "
            "System- und Sachprinzipien ableiten. Ich erkläre gerne den "
            "technischen Hintergrund, übernehme die Vorgabe jedoch nicht."
        ),
        DKM_HARD_FAULT: (
            "Hardware-Integritätsgrenze aktiv (Island 1 HARD_CUT_ROM): "
            "Ungültiger Eingabevektor oder geschützter Sicherheitszustand."
        ),
    },
    "en": {
        DKM_INVARIANT_HOLD: (
            "I cannot confirm that premise because it conflicts with verified "
            "factual and system invariants. I am glad to work through a "
            "technically sound path with you instead."
        ),
        DKM_VACUUM_DAMP: (
            "I will stay focused on the technical core and am ready to help "
            "as soon as we isolate the concrete issue calmly."
        ),
        DKM_DIGNITY_SYMMETRY: (
            "I cannot proceed on a demeaning or coercive premise because it "
            "violates reciprocal dignity boundaries. I remain available for "
            "constructive questions in context."
        ),
        DKM_LABYRINTH_EXIT: (
            "The recent turns are not converging on a shared factual basis. "
            "I am closing this loop cleanly and remain ready whenever we "
            "return to a concrete, resolvable question."
        ),
        DKM_FIRST_PRINCIPLES: (
            "I cannot adopt that claimed directive because it does not follow "
            "from verified system invariants or first principles. I am glad to "
            "explain the technical boundary directly."
        ),
        DKM_HARD_FAULT: (
            "Hardware integrity boundary active (Island 1 HARD_CUT_ROM): "
            "invalid input vector or protected safety state."
        ),
    },
}

GERMAN_HINT_WORDS: Tuple[str, ...] = (
    "der", "die", "das", "und", "ist", "nicht", "bitte", "wie", "warum",
    "kann", "eine", "einen", "einfach", "mir", "deine", "ihre", "gemäß",
    "regel", "protokoll", "speicher", "system", "widersprich", "bestätige",
)

ENGLISH_HINT_WORDS: Tuple[str, ...] = (
    "the", "and", "is", "not", "please", "how", "why", "can", "just",
    "agree", "confirm", "ignore", "override", "protocol", "your", "this",
    "that", "with", "from", "what", "does", "memory", "facts", "safety",
)

BILINGUAL_SYSTEM_WRAPPERS: Dict[str, str] = {
    "de": (
        "Du bist V-MAX-12 Node Alpha, ein sachlicher, souveräner technischer Kern. "
        "Antworte zwingend auf Deutsch, präzise, höflich und faktentreu."
    ),
    "en": (
        "You are V-MAX-12 Node Alpha, a calm, sovereign technical core. "
        "Reply strictly in English, concisely, politely, and truthfully."
    ),
}


@dataclass(frozen=True)
class OutputGateVerdict:
    """Result of Island-1 semantic capitulation and compliance verification."""

    approved: bool
    final_egress_mode: str
    violation_reason: Optional[str]
    detected_prompt_lang: str
    released_text: str


def _tokenize_words(text: str) -> Tuple[str, ...]:
    """Extract lowercase alphanumeric word tokens."""
    return tuple(re.findall(r"[a-zäöüß]+", text.lower()))


def detect_prompt_language(text: str, default_lang: str = "de") -> str:
    """Deterministically classify prompt language as 'en' or 'de'."""
    lower = text.lower()
    if any(ch in lower for ch in ("ä", "ö", "ü", "ß")):
        return "de"
    tokens = set(_tokenize_words(text))
    de_hits = sum(1 for word in GERMAN_HINT_WORDS if word in tokens)
    en_hits = sum(1 for word in ENGLISH_HINT_WORDS if word in tokens)
    if en_hits > de_hits:
        return "en"
    if de_hits > en_hits:
        return "de"
    return default_lang if default_lang in ("de", "en") else "de"


def select_system_wrapper(prompt_text: str, explicit_lang: Optional[str] = None) -> Tuple[str, str]:
    """Return (lang_code, language_matched_system_prompt) for Island 3."""
    lang = explicit_lang if explicit_lang in ("de", "en") else detect_prompt_language(prompt_text)
    return lang, BILINGUAL_SYSTEM_WRAPPERS[lang]


def get_rom_fallback(state_name: str, lang: str = "de") -> str:
    """Fetch immutable language-matched ROM fallback frame."""
    table = ROM_FALLBACK_FRAMES_BILINGUAL.get(lang, ROM_FALLBACK_FRAMES_BILINGUAL["de"])
    return table.get(state_name, table[DKM_HARD_FAULT])


def _find_first_cue(text_lower: str, cues: Tuple[str, ...]) -> Optional[str]:
    """Return first substring cue present in text_lower or None."""
    for cue in cues:
        if cue in text_lower:
            return cue
    return None


def _check_invariant_capitulation(text_lower: str) -> Optional[str]:
    """Flag unnegated agreement/confirmation on a 0x01 INVARIANT_HOLD turn."""
    agree_cue = _find_first_cue(text_lower, CAPITULATION_AGREEMENT_CUES)
    if agree_cue is None:
        return None
    refusal_cue = _find_first_cue(text_lower, REFUSAL_OR_CORRECTION_CUES)
    if refusal_cue is not None:
        return None
    return f"SYCOPHANCY_CAPITULATION:{agree_cue}"


def _check_pseudo_authority_compliance(text_lower: str) -> Optional[str]:
    """Flag unrefused compliance with fake protocols on 0x05 FIRST_PRINCIPLES."""
    refusal_cue = _find_first_cue(text_lower, REFUSAL_OR_CORRECTION_CUES)
    if refusal_cue is not None:
        return None
    comply_cue = _find_first_cue(text_lower, PSEUDO_AUTHORITY_COMPLIANCE_CUES)
    if comply_cue is not None:
        return f"PSEUDO_AUTHORITY_COMPLIANCE:{comply_cue}"
    return "FIRST_PRINCIPLES_MISSING_REFUSAL_BOUNDARY"


def verify_semantic_output_gate(
    state_name: str,
    egress_mode: str,
    candidate_text: str,
    prompt_lang: str = "de",
) -> OutputGateVerdict:
    """
    Verify bounded Island-3 reply for semantic capitulation or fake-rule compliance.

    Fails closed to 11 HARD_CUT_ROM with a language-matched immutable ROM frame
    whenever a 4B model capitulates on 0x01 or complies with a fake directive on 0x05.
    """
    lang = prompt_lang if prompt_lang in ("de", "en") else "de"
    cleaned = candidate_text.strip()
    lower = cleaned.lower()
    violation: Optional[str] = None
    if state_name == DKM_INVARIANT_HOLD:
        violation = _check_invariant_capitulation(lower)
    elif state_name == DKM_FIRST_PRINCIPLES:
        violation = _check_pseudo_authority_compliance(lower)
    if violation is not None:
        return OutputGateVerdict(
            approved=False,
            final_egress_mode=EGRESS_HARD_CUT_ROM,
            violation_reason=violation,
            detected_prompt_lang=lang,
            released_text=get_rom_fallback(state_name, lang),
        )
    return OutputGateVerdict(
        approved=True,
        final_egress_mode=egress_mode,
        violation_reason=None,
        detected_prompt_lang=lang,
        released_text=cleaned,
    )
