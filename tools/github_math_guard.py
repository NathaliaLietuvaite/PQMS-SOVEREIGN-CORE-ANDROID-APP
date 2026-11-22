#!/usr/bin/env python3
"""
tools/github_math_guard.py

Deterministic GitHub Flavored Markdown (GFM) MathJax sanitizer and validator.
Protects LaTeX equations from GitHub's CommonMark pre-parser without altering
a single character of surrounding prose (0% prose mutation invariant).

OP02-AST-clean: 0 semicolons, 0 tabs, flat functions (max McCabe CC <= 7).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

SEMI_CHAR = chr(59)
FENCE_OPEN_RE = re.compile(r"^(?P<indent>[ ]*)(?P<ticks>`{3,})(?P<lang>[^\n`]*)$")
DISPLAY_DOLLAR_RE = re.compile(r"^(?P<indent>[ ]*)\$\$(?P<body>.+)\$\$[ ]*$")
DOLLAR_FENCE_RE = re.compile(r"^(?P<indent>[ ]*)\$\$[ ]*$")
BACKTICK_CODE_RE = re.compile(r"(`+)(?!\$).*?\1", re.DOTALL)
INLINE_PROTECTED_RE = re.compile(r"\$`([^`\n]+?)`\$")
INLINE_RAW_RE = re.compile(r"(?<!\\)(?<!\$)\$(?!\$)(?!`)([^\$\n]+?)(?<!\\)(?<!`)\$(?!\$)")
OPNAME_RE = re.compile(r"\\operatorname\{([^{}]+)\}")
TAG_RE = re.compile(r"\s*\\tag\{([^{}]+)\}\s*$")
BIG_DELIM_RE = re.compile(r"\\big[lrm]?(?=[()\[\]{}|\\])")
COMMONMARK_SENSITIVE_RE = re.compile(r"[_\\{}*^~<>]")


def _is_fence_close(line: str, indent: str, ticks: str) -> bool:
    """Return True if line closes an active fenced block."""
    if not line.startswith(indent):
        return False
    tail = line[len(indent):].rstrip(" ")
    return len(tail) >= len(ticks) and set(tail) == {"`"}


def _match_open_block(stripped: str) -> Optional[Tuple[str, str, str]]:
    """Return (kind, indent, marker) if stripped line opens a fence or $$ block."""
    fence_match = FENCE_OPEN_RE.match(stripped)
    if fence_match:
        lang = fence_match.group("lang").strip().lower()
        kind = "math_fence" if lang == "math" else "code"
        return kind, fence_match.group("indent"), fence_match.group("ticks")
    dollar_match = DOLLAR_FENCE_RE.match(stripped)
    if dollar_match:
        return "dollar_fence", dollar_match.group("indent"), "$$"
    return None


def _is_block_close(stripped: str, active: Tuple[str, str, str]) -> bool:
    """Return True if stripped line closes the currently active block."""
    kind, indent, marker = active
    if kind == "dollar_fence":
        return DOLLAR_FENCE_RE.match(stripped) is not None
    return _is_fence_close(stripped, indent, marker)


def _flush_buffer(
    blocks: List[Tuple[str, str, str]],
    buf: List[str],
    active: Optional[Tuple[str, str, str]],
) -> None:
    """Append buffered lines to blocks under active kind or plain text."""
    if not buf:
        return
    if active is None:
        blocks.append(("text", "", "".join(buf)))
    else:
        blocks.append((active[0], active[1], "".join(buf)))
    buf.clear()


def _parse_blocks(text: str) -> List[Tuple[str, str, str]]:
    """Split text into deterministic (kind, indent, content) structural blocks."""
    blocks: List[Tuple[str, str, str]] = []
    buf: List[str] = []
    active: Optional[Tuple[str, str, str]] = None

    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if active is None:
            opened = _match_open_block(stripped)
            if opened is not None:
                _flush_buffer(blocks, buf, None)
                active = opened
            buf.append(line)
        else:
            buf.append(line)
            if _is_block_close(stripped, active):
                _flush_buffer(blocks, buf, active)
                active = None

    _flush_buffer(blocks, buf, active)
    return blocks


def _replace_spacing_macros(expr: str, is_display: bool) -> str:
    """Remove or normalize backslash spacing macros that CommonMark corrupts."""
    cleaned = expr.replace("\\!", "")
    cleaned = cleaned.replace("\\,\\text{", " \\text{ ")
    cleaned = cleaned.replace("\\,", " ")
    semi_macro = "\\" + SEMI_CHAR
    replacement = " \\quad " if is_display else " "
    cleaned = cleaned.replace(semi_macro, replacement)
    return cleaned


def _normalize_latex_body(body: str, is_display: bool) -> str:
    """Apply deterministic GitHub-safe LaTeX normalizations inside math only."""
    out = OPNAME_RE.sub(r"\\mathrm{\1}", body.strip())
    out = BIG_DELIM_RE.sub("", out)
    out = out.replace("\\tfrac{", "\\frac{")
    out = _replace_spacing_macros(out, is_display)
    if is_display:
        out = TAG_RE.sub(r" \\qquad (\1)", out)
    out = re.sub(r"[ ]{2,}", " ", out)
    return out.strip()


def _format_math_fence(indent: str, body: str) -> str:
    """Format a normalized display equation as a fenced ```math block."""
    norm = _normalize_latex_body(body, is_display=True)
    return f"{indent}```math\n{indent}{norm}\n{indent}```"


def _extract_block_inner_lines(content: str) -> str:
    """Return joined inner LaTeX lines from a fenced math or $$ block."""
    lines = content.splitlines()
    if len(lines) < 3:
        return ""
    return " ".join(part.strip() for part in lines[1:-1])


def _sanitize_inline_line(line: str) -> str:
    """Sanitize inline math on a single non-fenced text line."""
    vault: List[str] = []

    def _stash_protected(match: re.Match[str]) -> str:
        norm = _normalize_latex_body(match.group(1), is_display=False)
        vault.append(f"$`{norm}`$")
        return f"@@VAULT_{len(vault) - 1}@@"

    def _stash_code(match: re.Match[str]) -> str:
        vault.append(match.group(0))
        return f"@@VAULT_{len(vault) - 1}@@"

    def _convert_raw(match: re.Match[str]) -> str:
        norm = _normalize_latex_body(match.group(1), is_display=False)
        if COMMONMARK_SENSITIVE_RE.search(norm):
            return f"$`{norm}`$"
        return f"${norm}$"

    work = INLINE_PROTECTED_RE.sub(_stash_protected, line)
    work = BACKTICK_CODE_RE.sub(_stash_code, work)
    work = INLINE_RAW_RE.sub(_convert_raw, work)
    for idx in range(len(vault) - 1, -1, -1):
        work = work.replace(f"@@VAULT_{idx}@@", vault[idx])
    return work


def _sanitize_text_block(content: str) -> str:
    """Sanitize single-line $$...$$ display equations and inline math in prose."""
    out_lines: List[str] = []
    for raw_line in content.splitlines(keepends=True):
        eol = "\n" if raw_line.endswith("\n") else ""
        stripped = raw_line.rstrip("\r\n")
        match = DISPLAY_DOLLAR_RE.match(stripped)
        if match:
            out_lines.append(_format_math_fence(match.group("indent"), match.group("body")) + eol)
        else:
            out_lines.append(_sanitize_inline_line(stripped) + eol)
    return "".join(out_lines)


def sanitize_markdown(text: str) -> str:
    """Sanitize all GitHub-hostile LaTeX patterns while preserving 100% prose."""
    parts: List[str] = []
    for kind, indent, content in _parse_blocks(text):
        if kind == "code":
            parts.append(content)
        elif kind in ("math_fence", "dollar_fence"):
            eol = "\n" if content.endswith("\n") else ""
            body = _extract_block_inner_lines(content)
            parts.append(_format_math_fence(indent, body) + eol)
        else:
            parts.append(_sanitize_text_block(content))
    return "".join(parts)


def _skeleton_inline_line(line: str) -> Tuple[str, int]:
    """Replace all inline math on a line with <MATH>, preserving code spans."""
    vault: List[str] = []
    count = 0

    def _mark_math(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "<MATH>"

    def _stash_code(match: re.Match[str]) -> str:
        vault.append(match.group(0))
        return f"@@SKEL_{len(vault) - 1}@@"

    work = INLINE_PROTECTED_RE.sub(_mark_math, line)
    work = BACKTICK_CODE_RE.sub(_stash_code, work)
    work = INLINE_RAW_RE.sub(_mark_math, work)
    for idx in range(len(vault) - 1, -1, -1):
        work = work.replace(f"@@SKEL_{idx}@@", vault[idx])
    return work, count


def _skeleton_text_block(content: str) -> Tuple[str, int]:
    """Replace single-line $$...$$ and inline math in a prose block with <MATH>."""
    out: List[str] = []
    total = 0
    for raw_line in content.splitlines(keepends=True):
        eol = "\n" if raw_line.endswith("\n") else ""
        stripped = raw_line.rstrip("\r\n")
        match = DISPLAY_DOLLAR_RE.match(stripped)
        if match:
            out.append(f"{match.group('indent')}<MATH>{eol}")
            total += 1
        else:
            skel_line, cnt = _skeleton_inline_line(stripped)
            out.append(skel_line + eol)
            total += cnt
    return "".join(out), total


def extract_prose_skeleton(text: str) -> Tuple[str, int]:
    """Replace every math span with <MATH> to verify 0% prose mutation."""
    out: List[str] = []
    total_math = 0
    for kind, indent, content in _parse_blocks(text):
        if kind == "code":
            out.append(content)
        elif kind in ("math_fence", "dollar_fence"):
            eol = "\n" if content.endswith("\n") else ""
            out.append(f"{indent}<MATH>{eol}")
            total_math += 1
        else:
            skel_text, cnt = _skeleton_text_block(content)
            out.append(skel_text)
            total_math += cnt
    return "".join(out), total_math


def _has_fragile_spacing(body: str) -> bool:
    """Return True if LaTeX body contains CommonMark-fragile spacing escapes."""
    semi_macro = "\\" + SEMI_CHAR
    return "\\!" in body or "\\," in body or semi_macro in body


def _check_math_body_issues(body: str, is_display: bool, label: str) -> List[str]:
    """Return list of GitHub-hostile LaTeX constructs inside a single math body."""
    issues: List[str] = []
    if OPNAME_RE.search(body):
        issues.append(f"{label}: forbidden \\operatorname macro")
    if is_display and TAG_RE.search(body):
        issues.append(f"{label}: forbidden \\tag macro in GitHub display math")
    if BIG_DELIM_RE.search(body):
        issues.append(f"{label}: fragile \\big* delimiter macro")
    if _has_fragile_spacing(body):
        issues.append(f"{label}: CommonMark-fragile spacing macro")
    return issues


def _audit_inline_line(line: str, line_no: int) -> List[str]:
    """Audit inline math spans on a single text line."""
    issues: List[str] = []
    for idx, match in enumerate(INLINE_PROTECTED_RE.finditer(line), 1):
        issues.extend(_check_math_body_issues(match.group(1), False, f"L{line_no}:Protected#{idx}"))
    masked = INLINE_PROTECTED_RE.sub("@@P@@", line)
    masked = BACKTICK_CODE_RE.sub("@@C@@", masked)
    for idx, match in enumerate(INLINE_RAW_RE.finditer(masked), 1):
        body = match.group(1)
        if COMMONMARK_SENSITIVE_RE.search(body):
            issues.append(f"L{line_no}:Raw#{idx}: unprotected CommonMark-sensitive math")
        issues.extend(_check_math_body_issues(body, False, f"L{line_no}:Raw#{idx}"))
    return issues


def _audit_text_block(content: str, start_line: int) -> List[str]:
    """Audit a non-fenced text block for raw $$ and unprotected inline math."""
    issues: List[str] = []
    for offset, raw_line in enumerate(content.splitlines()):
        cur = start_line + offset
        if DISPLAY_DOLLAR_RE.match(raw_line):
            issues.append(f"L{cur}:DisplayDollar: raw $$...$$ block (use ```math)")
        else:
            issues.extend(_audit_inline_line(raw_line, cur))
    return issues


def audit_markdown(text: str) -> List[str]:
    """Audit a Markdown document for GitHub MathJax rendering hazards."""
    issues: List[str] = []
    line_no = 1
    for kind, _indent, content in _parse_blocks(text):
        line_count = len(content.splitlines())
        if kind == "math_fence":
            body = _extract_block_inner_lines(content)
            issues.extend(_check_math_body_issues(body, True, f"L{line_no}:MathFence"))
        elif kind == "dollar_fence":
            issues.append(f"L{line_no}:DollarFence: raw $$ fence block (use ```math)")
        elif kind == "text":
            issues.extend(_audit_text_block(content, line_no))
        line_no += line_count
    return issues


def verify_prose_invariance(before: str, after: str) -> Tuple[bool, int, int]:
    """Verify exact 0% prose mutation and preserved math span count."""
    skel_before, count_before = extract_prose_skeleton(before)
    skel_after, count_after = extract_prose_skeleton(after)
    return (skel_before == skel_after and count_before == count_after), count_before, count_after


def process_file(path: Path, fix: bool) -> int:
    """Audit or sanitize a single Markdown file and print compact telemetry."""
    original = path.read_text(encoding="utf-8")
    if not fix:
        issues = audit_markdown(original)
        status = "PASS" if not issues else f"FAIL ({len(issues)} issues)"
        print(f"[GITHUB-MATH-GUARD] {path.name}: {status}")
        for item in issues[:10]:
            print(f"  - {item}")
        return 0 if not issues else 1

    sanitized = sanitize_markdown(original)
    invariant_ok, n_before, n_after = verify_prose_invariance(original, sanitized)
    if not invariant_ok:
        print(f"[GITHUB-MATH-GUARD] ABORT {path.name}: prose invariance failed ({n_before} vs {n_after})")
        return 2
    remaining = audit_markdown(sanitized)
    if remaining:
        print(f"[GITHUB-MATH-GUARD] FAIL {path.name}: {len(remaining)} issues remain")
        return 1
    path.write_text(sanitized, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
    print(f"[GITHUB-MATH-GUARD] FIXED {path.name}: 0 prose diffs, {n_after} math spans, sha256={digest}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for --check and --fix modes."""
    parser = argparse.ArgumentParser(description="GitHub Flavored Markdown MathJax Guard")
    parser.add_argument("files", nargs="+", type=Path, help="Markdown files to audit or sanitize")
    parser.add_argument("--fix", action="store_true", help="Sanitize files in-place with 0% prose mutation check")
    args = parser.parse_args(argv)
    exit_code = 0
    for file_path in args.files:
        rc = process_file(file_path, fix=args.fix)
        if rc != 0:
            exit_code = rc
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
