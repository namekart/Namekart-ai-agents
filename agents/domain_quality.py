"""
Shared deterministic domain-quality rules for bulk + linguistic filtering.

Both stages use the same hard-reject patterns so junk is eliminated early
and scoring stays consistent across the pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.config import settings


# ── TLD tiers ───────────────────────────────────────────────────────────────

PREMIUM_TLDS = frozenset({"com"})
STRONG_TLDS = frozenset({"io", "ai", "net", "co", "app", "org", "me"})
WEAK_TLDS = frozenset({"info", "biz", "online", "site", "club", "link", "fun"})
BLOCKED_TLDS = frozenset({
    "xyz", "top", "click", "win", "vip", "work", "live", "store", "shop",
    "space", "website", "icu", "cfd", "sbs", "bond", "cam", "rest", "buzz",
    "monster", "quest", "lat", "cyou", "autos", "boats", "homes", "lol",
})

# ── Pattern library (shared with linguistic agent) ─────────────────────────

_KEYBOARD_MASH_RE = re.compile(
    r"(asdf|sdfg|dfgh|fghj|ghjk|hjkl|lkjh|kjhg|jhgf|hgfd|gfds|fdsa"
    r"|qwer|wert|erty|rtyu|tyui|yuio|uiop|poiu|oiuy|iuyt|ytre|treq"
    r"|zxcv|xcvb|cvbn|vbnm|zzzz|xxx|yyy|zzz)"
)
_REPEAT_RE = re.compile(r"(.)\1{2,}")
_RANDOM_RE = re.compile(r"^[bcdfghjklmnpqrstvwxyz]{4,}$")
_SINGLE_CHAR_SEGMENT_RE = re.compile(r"^([a-z]-){2,}[a-z]$")
_VOWEL_CLUSTER_RE = re.compile(r"[aeiou]{3,}")
_CONSONANT_CLUSTER_RE = re.compile(r"[bcdfghjklmnpqrstvwxyz]{4,}")

_COMMON_WORDS = frozenset({
    "app", "hub", "lab", "pay", "buy", "run", "pro", "net", "web", "tech",
    "go", "data", "care", "flow", "link", "shop", "work", "fit", "help",
    "find", "fast", "best", "top", "soft", "code", "cloud", "smart", "next",
    "open", "free", "real", "live", "home", "team", "teams", "base", "list", "grow",
    "health", "legal", "money", "trade", "build", "design", "track", "market",
    "invest", "agency", "media", "brand", "digital", "global", "local", "search",
    "therapist", "therapy", "finance", "bank", "learn", "hire", "book", "call",
    "loop", "dev", "lead", "neural", "neo", "mail", "open", "stack", "idea",
})

_POWER_WORDS = frozenset({
    "hub", "lab", "pro", "nova", "peak", "flow", "link", "next", "smart",
    "swift", "bold", "bright", "clear", "prime", "rise", "spark", "forge",
    "craft", "edge", "core", "zone", "gate", "base", "nest",
})

_GEO_PREFIXES = frozenset({
    "newyork", "losangeles", "chicago", "london", "paris", "berlin", "tokyo",
    "mumbai", "delhi", "sydney", "toronto", "boston", "dallas", "miami",
})

_HYPER_KEYWORD_SUFFIXES = (
    "insurance", "lawyer", "attorney", "marketing", "hosting", "software",
    "services", "solutions", "consulting", "directory", "reviews", "deals",
)


@dataclass(frozen=True)
class DomainFeatures:
    domain_name: str
    stem: str
    tld: str
    length: int
    vowel_ratio: float
    has_digit: bool
    has_dash: bool
    max_consonant_run: int
    is_keyboard_mash: bool
    is_repeat_char: bool
    is_consonant_only: bool
    is_single_char_segments: bool
    has_vowel_cluster: bool
    has_long_consonant_cluster: bool
    has_word_root: bool
    has_power_word: bool
    is_geo_keyword: bool
    is_hyper_keyword: bool


def parse_domain(domain_name: str) -> DomainFeatures:
    normalized = domain_name.strip().lower()
    stem = normalized.split(".", 1)[0]
    tld = normalized.rsplit(".", 1)[-1] if "." in normalized else "com"
    length = len(stem)

    vowels = sum(c in "aeiou" for c in stem)
    vowel_ratio = vowels / max(length, 1)
    has_digit = any(c.isdigit() for c in stem)
    has_dash = "-" in stem

    max_consonant_run = max(
        (len(m.group()) for m in re.finditer(r"[bcdfghjklmnpqrstvwxyz]+", stem)),
        default=0,
    )

    is_keyboard_mash = bool(_KEYBOARD_MASH_RE.search(stem))
    is_repeat_char = bool(_REPEAT_RE.search(stem))
    is_consonant_only = bool(_RANDOM_RE.match(stem))
    is_single_char_segments = bool(_SINGLE_CHAR_SEGMENT_RE.match(stem))
    has_vowel_cluster = bool(_VOWEL_CLUSTER_RE.search(stem))
    has_long_consonant_cluster = bool(_CONSONANT_CLUSTER_RE.search(stem))

    has_word_root = any(
        stem == w or stem.startswith(w) or stem.endswith(w)
        for w in _COMMON_WORDS
        if len(w) >= 3
    )
    has_power_word = any(pw in stem for pw in _POWER_WORDS)
    is_geo_keyword = any(stem.startswith(g) or stem.endswith(g) for g in _GEO_PREFIXES)
    is_hyper_keyword = any(stem.endswith(s) for s in _HYPER_KEYWORD_SUFFIXES) or len(stem) > 14

    return DomainFeatures(
        domain_name=normalized,
        stem=stem,
        tld=tld,
        length=length,
        vowel_ratio=vowel_ratio,
        has_digit=has_digit,
        has_dash=has_dash,
        max_consonant_run=max_consonant_run,
        is_keyboard_mash=is_keyboard_mash,
        is_repeat_char=is_repeat_char,
        is_consonant_only=is_consonant_only,
        is_single_char_segments=is_single_char_segments,
        has_vowel_cluster=has_vowel_cluster,
        has_long_consonant_cluster=has_long_consonant_cluster,
        has_word_root=has_word_root,
        has_power_word=has_power_word,
        is_geo_keyword=is_geo_keyword,
        is_hyper_keyword=is_hyper_keyword,
    )


def hard_reject_reason(features: DomainFeatures) -> str | None:
    """Instant reject — no further scoring. Returns reason or None."""

    if features.tld in BLOCKED_TLDS:
        return f"blocked tld .{features.tld}"

    if settings.bulk_block_weak_tlds and features.tld in WEAK_TLDS:
        return f"weak tld .{features.tld}"

    allowed_raw = settings.bulk_allowed_tlds.strip()
    if allowed_raw:
        allowed = frozenset(t.strip().lower() for t in allowed_raw.split(",") if t.strip())
        if features.tld not in allowed:
            return f"tld .{features.tld} not in allowed list"

    if features.length < settings.bulk_min_stem_length:
        return f"stem too short ({features.length})"

    if features.length > settings.bulk_max_stem_length:
        return f"stem too long ({features.length})"

    if settings.bulk_reject_digits and features.has_digit:
        return "contains digits"

    if settings.bulk_reject_dashes and features.has_dash:
        return "contains dash"

    junk_flags = (
        features.is_keyboard_mash,
        features.is_repeat_char,
        features.is_consonant_only,
        features.is_single_char_segments,
    )
    if any(junk_flags):
        return "junk/keyboard pattern"

    if features.has_long_consonant_cluster:
        return "consonant cluster"

    if features.vowel_ratio < 0.12:
        return "unpronounceable (no vowels)"

    if features.vowel_ratio > 0.72:
        return "unpronounceable (vowel-heavy)"

    if settings.bulk_reject_hyper_keywords and features.is_hyper_keyword:
        return "long/hyper keyword domain"

    if settings.bulk_reject_geo_keywords and features.is_geo_keyword:
        return "geo-keyword domain"

    return None


def score_brandability(features: DomainFeatures) -> tuple[int, str]:
    """
    Score 1–10 for brandability. Only call after hard_reject_reason is None.
    """
    score = 4
    reasons: list[str] = []

    # Length sweet spot — brandable names are short
    if 5 <= features.length <= 8:
        score += 3
        reasons.append("ideal length")
    elif features.length == 4 or 9 <= features.length <= 10:
        score += 1
        reasons.append("acceptable length")
    elif features.length <= 12:
        score -= 1
        reasons.append("long stem")
    else:
        score -= 3
        reasons.append("very long stem")

    # Pronounceability proxy
    if 0.28 <= features.vowel_ratio <= 0.52:
        score += 2
        reasons.append("good vowel balance")
    elif 0.22 <= features.vowel_ratio <= 0.58:
        score += 1
    else:
        score -= 1
        reasons.append("awkward vowel ratio")

    if features.max_consonant_run >= 3:
        score -= 2
        reasons.append("consonant run")
    elif features.max_consonant_run == 2 and features.length > 8:
        score -= 1

    if features.has_vowel_cluster:
        score -= 1
        reasons.append("vowel cluster")

    # TLD quality
    if features.tld in PREMIUM_TLDS:
        score += 2
        reasons.append("premium tld")
    elif features.tld in STRONG_TLDS:
        score += 1
        reasons.append("strong tld")
    elif features.tld in WEAK_TLDS:
        score -= 2
        reasons.append("weak tld")

    # Brand signals
    if features.has_power_word:
        score += 1
        reasons.append("power word")

    if features.has_word_root and 4 <= features.length <= 12:
        score += 1
        reasons.append("recognisable word")

    # Penalise generic dictionary-only stems (low resale novelty)
    if features.stem in _COMMON_WORDS and features.length <= 6:
        score -= 1
        reasons.append("generic dictionary word")

    score = max(1, min(10, score))
    reason = ", ".join(reasons) if reasons else "heuristic score"
    return score, reason


def passes_bulk_filter(domain_name: str) -> tuple[bool, int, str]:
    """Returns (passed, score, reason)."""
    features = parse_domain(domain_name)

    reject = hard_reject_reason(features)
    if reject:
        return False, 1, reject

    score, reason = score_brandability(features)
    passed = score >= settings.bulk_filter_pass_score
    if not passed:
        reason = f"below threshold ({score}<{settings.bulk_filter_pass_score}): {reason}"
    return passed, score, reason


def stem_has_brand_keyword(stem: str) -> bool:
    """True if stem embeds a recognisable brand/business word (e.g. lead+team, neural+bank)."""
    for word in sorted(_COMMON_WORDS, key=len, reverse=True):
        if len(word) >= 3 and word in stem:
            return True
    return False


def tld_linguistic_adjustment(tld: str) -> float:
    """Penalty applied to overall linguistic score for low-quality TLDs."""
    if tld in PREMIUM_TLDS:
        return 0.0
    if tld == "ai":
        return 0.0  # acquisition list is .ai-focused — do not penalise TLD
    if tld in STRONG_TLDS:
        return -0.2
    if tld in WEAK_TLDS:
        return -1.0
    if tld in BLOCKED_TLDS:
        return -3.0
    return -0.8


def adjusted_linguistic_score(overall: float, tld: str) -> float:
    return round(max(1.0, min(10.0, overall + tld_linguistic_adjustment(tld))), 2)


def passes_linguistic_gate(
    overall_score: float,
    tld: str,
    *,
    domain_name: str = "",
    pronounceability: int,
    memorability: int,
    spelling_ease: int,
    word_segmentation: int,
    brand_personality: int,
) -> tuple[bool, str]:
    """
    Multi-criteria linguistic gate — overall score alone is not enough.
    Returns (passed, reason_if_failed).
    """
    adjusted = adjusted_linguistic_score(overall_score, tld)

    if tld in BLOCKED_TLDS:
        return False, f"blocked tld .{tld}"

    if settings.linguistic_block_weak_tlds and tld in WEAK_TLDS:
        return False, f"weak tld .{tld}"

    stem = parse_domain(domain_name).stem if domain_name else ""
    has_brand_keyword = bool(domain_name and stem_has_brand_keyword(stem))
    brand_signal = max(word_segmentation, brand_personality)
    min_signal = settings.linguistic_min_brand_signal

    if adjusted < settings.linguistic_gate_threshold:
        brand_keyword_floor = settings.linguistic_gate_threshold - 0.75
        if not (
            has_brand_keyword
            and brand_personality >= settings.linguistic_min_brand_signal
            and adjusted >= brand_keyword_floor
        ):
            return False, f"overall {adjusted} < {settings.linguistic_gate_threshold}"

    if pronounceability < settings.linguistic_min_pronounceability:
        return False, f"pronounceability {pronounceability} < {settings.linguistic_min_pronounceability}"

    if memorability < settings.linguistic_min_memorability:
        return False, f"memorability {memorability} < {settings.linguistic_min_memorability}"

    if spelling_ease < settings.linguistic_min_spelling_ease:
        return False, f"spelling_ease {spelling_ease} < {settings.linguistic_min_spelling_ease}"

    if brand_signal < min_signal and not has_brand_keyword:
        return False, (
            f"no brand signal (segmentation {word_segmentation}, "
            f"personality {brand_personality} < {min_signal})"
        )

    min_dim = min(
        pronounceability,
        memorability,
        spelling_ease,
        word_segmentation,
        brand_personality,
    )

    if min_dim < settings.linguistic_min_dimension_score:
        brand_keyword_floor = settings.linguistic_gate_threshold - 0.75
        if (
            has_brand_keyword
            and adjusted >= brand_keyword_floor
            and pronounceability >= settings.linguistic_min_pronounceability
            and memorability >= settings.linguistic_min_memorability
            and min_dim >= 5
        ):
            pass
        else:
            return False, f"weakest dimension {min_dim} < {settings.linguistic_min_dimension_score}"

    return True, ""
