"""
Linguistic Agent — deterministic scoring engine.

All 8 brand-quality dimensions are computed by rule-based algorithms,
NOT by an LLM.  This gives identical output every run for the same input.

The LLM path (use_llm_linguistic=True) is preserved as an optional
override for research/testing but is OFF by default.
"""

import re
from typing import Iterable

import structlog

from app.config import settings
from agents.domain_quality import (
    adjusted_linguistic_score,
    parse_domain,
    passes_linguistic_gate,
)
from agents.llm_client import make_instructor_client
from prompts.linguistic import LINGUISTIC_SYSTEM, LINGUISTIC_USER
from schemas.linguistic import LinguisticReport


logger = structlog.get_logger()
client = make_instructor_client()


def evaluate_linguistic_gate(report: LinguisticReport) -> tuple[bool, float, str]:
    """Returns (passed, adjusted_overall_score, fail_reason)."""
    features = parse_domain(report.domain_name)
    passed, reason = passes_linguistic_gate(
        report.overall_linguistic_score,
        features.tld,
        domain_name=report.domain_name,
        pronounceability=report.pronounceability,
        memorability=report.memorability,
        spelling_ease=report.spelling_ease,
        word_segmentation=report.word_segmentation,
        brand_personality=report.brand_personality,
    )
    adjusted = adjusted_linguistic_score(report.overall_linguistic_score, features.tld)
    return passed, adjusted, reason


# ---------------------------------------------------------------------------
# Batch entry point (primary — used by pipeline)
# ---------------------------------------------------------------------------

def run_linguistic_agent_batch(domain_names: list[str]) -> list[LinguisticReport]:
    """
    Analyse multiple domains.

    When use_llm_linguistic=False (the default) every domain is scored
    by the deterministic engine — same input ⇒ same output, always.
    """
    if not domain_names:
        return []

    normalized = [d.strip().lower() for d in domain_names if d.strip()]
    if settings.enforce_deterministic_pipeline:
        return [score_linguistic_deterministic(d) for d in normalized]

    if not settings.use_llm_linguistic:
        return [score_linguistic_deterministic(d) for d in normalized]

    # ── LLM path (optional, non-deterministic) ─────────────────────────
    domain_list_str = "\n".join(f"- {d}" for d in normalized)
    messages = [
        {"role": "system", "content": LINGUISTIC_SYSTEM},
        {"role": "user", "content": LINGUISTIC_USER.format(domain_list=domain_list_str)},
    ]
    try:
        reports = client.chat.completions.create(
            model=settings.model_fast,
            response_model=Iterable[LinguisticReport],
            messages=messages,
            max_retries=3,
        )
        result_map: dict[str, LinguisticReport] = {}
        for r in reports:
            key = r.domain_name.strip().lower()
            r.domain_name = key
            result_map[key] = r

        final: list[LinguisticReport] = []
        for d in normalized:
            if d in result_map:
                final.append(result_map[d])
            else:
                logger.warning("Linguistic batch missing domain, using deterministic fallback", domain=d)
                final.append(score_linguistic_deterministic(d))
        return final

    except Exception as exc:
        logger.error("Linguistic batch failed, using deterministic fallback", error=str(exc))
        return [score_linguistic_deterministic(d) for d in normalized]


# ---------------------------------------------------------------------------
# Single-domain wrapper (backward compat)
# ---------------------------------------------------------------------------

def run_linguistic_agent(domain_name: str) -> LinguisticReport:
    """Convenience wrapper — analyse one domain."""
    results = run_linguistic_agent_batch([domain_name])
    return results[0]


# ---------------------------------------------------------------------------
# Deterministic scoring engine
# ---------------------------------------------------------------------------

# Common English words used for word-segmentation detection
_COMMON_WORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
    "had", "her", "was", "one", "our", "out", "day", "get", "has", "him",
    "his", "how", "man", "new", "now", "old", "see", "two", "way", "who",
    "boy", "did", "its", "let", "put", "say", "she", "too", "use",
    # Brand-relevant stems
    "app", "hub", "lab", "pay", "buy", "run", "pro", "net", "web", "tech",
    "go", "io", "ai", "data", "care", "flow", "link", "shop", "work", "fit",
    "help", "find", "fast", "best", "top", "soft", "code", "cloud", "smart",
    "next", "open", "free", "real", "live", "home", "team", "base", "list",
    "grow", "stay", "make", "give", "take", "move", "gain", "deal", "loan",
    "cash", "bank", "fund", "rent", "sale", "hire", "book", "call", "chat",
    "mail", "news", "blog", "learn", "teach", "study", "health", "legal",
    "money", "trade", "build", "design", "track", "manage", "launch",
    "connect", "market", "invest", "agency", "media", "brand", "digital",
    "global", "local", "social", "search", "review", "deliver", "service",
})

# Hard TLD-aware penalties (lower quality TLDs)
_TLD_QUALITY = {
    "com": 0, "net": -1, "org": -1, "io": -1, "ai": -1,
    "co": -1, "app": -1, "me": -1,
    "xyz": -4, "info": -3, "biz": -3, "click": -3,
    "online": -2, "site": -2, "club": -2, "link": -2,
    "top": -2, "vip": -2, "win": -2, "fun": -2,
}

# Patterns that indicate junk/random strings
_RANDOM_RE = re.compile(r"^[bcdfghjklmnpqrstvwxyz]{4,}$")   # no vowels, 4+ chars
_ALL_CONSONANTS_RE = re.compile(r"[bcdfghjklmnpqrstvwxyz]{4,}")  # cluster 4+
# Keyboard mash patterns: sequential home-row or qwerty sequences
_KEYBOARD_MASH_RE = re.compile(
    r"(asdf|sdfg|dfgh|fghj|ghjk|hjkl|lkjh|kjhg|jhgf|hgfd|gfds|fdsa"
    r"|qwer|wert|erty|rtyu|tyui|yuio|uiop|poiu|oiuy|iuyt|ytre|treq"
    r"|zxcv|xcvb|cvbn|vbnm|zzzz|xxx|yyy|zzz)"
)
# Repeating char sequences (e.g. 'aaabbb', 'zzz')
_REPEAT_RE = re.compile(r"(.)\1{2,}")
# Single-char-per-segment pattern: a-b-c-d style
_SINGLE_CHAR_SEGMENT_RE = re.compile(r"^([a-z]-){2,}[a-z]$")

# Brand personality power words
_POWER_WORDS = frozenset({
    "hub", "lab", "pro", "go", "nova", "peak", "flow", "link", "next",
    "smart", "swift", "bold", "bright", "clear", "prime", "rise", "spark",
    "forge", "craft", "edge", "core", "zone", "gate", "base", "nest",
})

# Industry-fit keyword sets
_INDUSTRY_KEYWORDS = {
    "fintech":    {"fin", "pay", "bank", "cash", "fund", "invest", "trade", "loan", "money"},
    "health":     {"health", "care", "med", "therapy", "therapist", "fit", "wellness"},
    "tech":       {"tech", "app", "code", "data", "cloud", "ai", "soft", "dev", "digital"},
    "ecommerce":  {"shop", "buy", "deal", "sale", "cart", "store", "market", "deliver"},
    "education":  {"learn", "teach", "study", "edu", "course", "skill", "tutor"},
    "hr":         {"hire", "job", "work", "recruit", "staff", "talent", "team"},
}

# Common suffix clichés that cap novelty
_CLICHE_SUFFIXES = ("ify", "ly", "hub", "ster", "io", "ify", "ify")
_CLICHE_PREFIXES = ("get", "my", "the", "best", "top", "a", "e", "i")

# Cross-language safety blocklist (stems known to have negative meanings in major languages)
_UNSAFE_STEMS = frozenset({
    # Some well-known examples; production list would be larger
    "mist", "fart", "suck", "damn", "hell", "crap", "kunt", "fick",
    "shit", "kill", "hate", "dead", "pain", "kill",
})


def score_linguistic_deterministic(domain_name: str) -> LinguisticReport:
    """
    Compute all 8 linguistic dimensions using pure rules.
    Returns identical output for identical input — no LLM involved.
    """
    features = parse_domain(domain_name)
    stem = features.stem
    tld = features.tld
    length = features.length
    vowel_ratio = features.vowel_ratio
    has_digit = features.has_digit
    has_dash = features.has_dash
    vowel_count = round(vowel_ratio * max(length, 1))

    is_junk = (
        features.is_keyboard_mash
        or features.is_repeat_char
        or features.is_consonant_only
        or features.is_single_char_segments
        or features.tld in {"xyz", "top", "click", "win", "vip"}
    )

    if is_junk:
        return LinguisticReport(
            domain_name=features.domain_name,
            pronounceability=2,
            memorability=2,
            spelling_ease=3,
            cross_language_safety=5,
            word_segmentation=2,
            brand_personality=1,
            industry_fit=1,
            novelty_score=1,
        )

    # ── 1. Pronounceability (1–10) ──────────────────────────────────────────
    # Start conservative — bulk pass alone should not auto-score high here.
    pronounceability = 6
    if vowel_ratio < 0.15:
        pronounceability -= 4   # almost no vowels → very hard to say
    elif vowel_ratio < 0.25:
        pronounceability -= 2
    elif vowel_ratio > 0.60:
        pronounceability -= 1   # too many vowels → awkward

    max_consonant_run = features.max_consonant_run
    if max_consonant_run >= 4:
        pronounceability -= 3
    elif max_consonant_run == 3:
        pronounceability -= 1

    if has_digit:
        pronounceability -= 2
    if has_dash:
        pronounceability -= 1
    if _RANDOM_RE.match(stem):
        pronounceability -= 2   # pure consonant string

    pronounceability = max(1, min(10, pronounceability))

    # ── 2. Memorability (1–10) ───────────────────────────────────────────────
    syllables = max(1, round(vowel_count))
    memorability = 6
    if length < 3:
        memorability = 4
    elif length > 14:
        memorability -= 3
    elif length > 10:
        memorability -= 1

    if syllables > 4:
        memorability -= 2
    elif syllables == 1 and length > 6:
        memorability -= 1

    # Bonus if stem contains a recognisable word root
    if any(stem.startswith(w) or stem.endswith(w) for w in _COMMON_WORDS if len(w) >= 3):
        memorability = min(10, memorability + 1)
    if has_digit or has_dash:
        memorability -= 1

    memorability = max(1, min(10, memorability))

    # ── 3. Spelling Ease (1–10) ──────────────────────────────────────────────
    spelling_ease = 7
    ambiguous = ("xz", "zx", "qw", "wq", "kn", "ph", "ck", "gh")
    if any(p in stem for p in ambiguous):
        spelling_ease -= 2
    if has_digit:
        spelling_ease -= 3
    if has_dash:
        spelling_ease -= 2
    if length > 12:
        spelling_ease -= 2
    elif length > 9:
        spelling_ease -= 1
    # Repeated chars that cause confusion (e.g. lkjhgfdsa)
    if _RANDOM_RE.match(stem):
        spelling_ease -= 3

    spelling_ease = max(1, min(10, spelling_ease))

    # ── 4. Cross-Language Safety (1–10) ──────────────────────────────────────
    # Default 8 (unknown is safer than assuming perfect).
    # Penalise known problematic stems.
    cross_language_safety = 8
    if stem in _UNSAFE_STEMS or any(bad in stem for bad in _UNSAFE_STEMS if len(bad) >= 4):
        cross_language_safety = 2
    elif has_digit or has_dash:
        cross_language_safety = 7  # harder to localize

    cross_language_safety = max(1, min(10, cross_language_safety))

    # ── 5. Word Segmentation (1–10) ──────────────────────────────────────────
    word_segmentation = 3
    if stem in _COMMON_WORDS:
        word_segmentation = 10
    elif any(stem.startswith(w) or stem.endswith(w) for w in _COMMON_WORDS if len(w) >= 4):
        word_segmentation = 8
    elif any(len(w) >= 3 and w in stem for w in _COMMON_WORDS):
        word_segmentation = 7  # compound: leadteam, neuralbank, myloop
    elif has_digit or has_dash:
        word_segmentation = 4
    elif 4 <= length <= 8 and vowel_ratio >= 0.25:
        word_segmentation = 5  # short coined — weak signal only
    if _RANDOM_RE.match(stem):
        word_segmentation = 2

    word_segmentation = max(1, min(10, word_segmentation))

    # ── 6. Brand Personality (1–10) ──────────────────────────────────────────
    brand_personality = 4
    if any(pw in stem for pw in _POWER_WORDS):
        brand_personality = 8
    if any(k in stem for k in ("team", "teams", "bank", "build", "loop", "dev", "lead", "learn", "data", "neural", "neo")):
        brand_personality = max(brand_personality, 7)
    if stem.endswith("ify"):
        brand_personality = max(brand_personality, 7)
    if stem.endswith("ly"):
        brand_personality = max(brand_personality, 6)
    if stem.endswith("er") or stem.endswith("or"):
        brand_personality = max(brand_personality, 6)
    if has_digit or _RANDOM_RE.match(stem):
        brand_personality = 2

    if features.has_word_root:
        pronounceability = min(10, pronounceability + 1)
        brand_personality = max(brand_personality, 6)

    brand_personality = max(1, min(10, brand_personality))

    # ── 7. Industry Fit (1–10) ───────────────────────────────────────────────
    industry_fit = 3   # default: no clear vertical
    for _industry, keywords in _INDUSTRY_KEYWORDS.items():
        if any(k in stem for k in keywords):
            industry_fit = 8
            break
    if stem in _COMMON_WORDS:
        industry_fit = max(industry_fit, 6)
    if _RANDOM_RE.match(stem) or has_digit:
        industry_fit = 1

    industry_fit = max(1, min(10, industry_fit))

    # ── 8. Novelty Score (1–10) ──────────────────────────────────────────────
    novelty_score = 5
    if stem.endswith(_CLICHE_SUFFIXES):
        novelty_score = min(novelty_score, 5)   # suffix cliché cap
    if stem.startswith(_CLICHE_PREFIXES):
        novelty_score = min(novelty_score, 5)
    if stem in _COMMON_WORDS:
        novelty_score = 4   # real dictionary word, not novel
    if _RANDOM_RE.match(stem):
        novelty_score = 1   # random gibberish
    if has_digit:
        novelty_score = max(1, novelty_score - 2)
    # Short punchy invented word (4–6 chars, not in dictionary) = novel
    if 4 <= length <= 7 and stem not in _COMMON_WORDS and not has_digit and not has_dash:
        novelty_score = min(10, novelty_score + 1)

    novelty_score = max(1, min(10, novelty_score))

    # Penalise only empty coined .ai suffixes — not names with real word roots
    if tld == "ai" and 5 <= length <= 11:
        has_root = any(len(w) >= 3 and w in stem for w in _COMMON_WORDS)
        if re.search(r"(wise|hub|tech|soft|code|link|flow|ify|bot|gen|gpt)$", stem) and not has_root:
            memorability = max(1, memorability - 2)
            brand_personality = max(1, brand_personality - 2)
            novelty_score = max(1, novelty_score - 1)
        elif not has_root and not re.search(r"(team|bank|build|loop|dev|lead|learn|data|neo)", stem):
            memorability = max(1, memorability - 1)
            brand_personality = max(1, brand_personality - 1)

    return LinguisticReport(
        domain_name=features.domain_name,
        pronounceability=pronounceability,
        memorability=memorability,
        spelling_ease=spelling_ease,
        cross_language_safety=cross_language_safety,
        word_segmentation=word_segmentation,
        brand_personality=brand_personality,
        industry_fit=industry_fit,
        novelty_score=novelty_score,
        # overall_linguistic_score is recomputed by the Pydantic model_validator
    )
