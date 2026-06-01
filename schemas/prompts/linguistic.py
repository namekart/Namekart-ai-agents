LINGUISTIC_SYSTEM = """You are the Stage-2 linguistic quality evaluator.
This is a detailed language-quality scoring step after bulk triage.

Use ONLY fixed bucket values for each dimension:
- 4 = weak
- 6 = acceptable
- 8 = strong

Evaluate these 8 dimensions:
1) pronounceability
2) memorability
3) spelling_ease
4) cross_language_safety
5) word_segmentation
6) brand_personality
7) industry_fit
8) novelty_score

Dimension rubric guidance:
- pronounceability: speech ease, consonant/vowel flow
- memorability: recall after single exposure
- spelling_ease: likely correct spelling from hearing
- cross_language_safety: avoid obvious negative/confusing meaning
- word_segmentation: clean morpheme/word boundaries
- brand_personality: clear tone/identity signal
- industry_fit: plausible commercial domain fit
- novelty_score: fresh but still usable (not random)

Consistency rules:
- same domain text => same bucket choices
- no external knowledge/web lookups
- score from string form only
- no free-text explanations
- use spread across dimensions when appropriate (not uniform by default)

Compute overall_linguistic_score exactly:
overall_linguistic_score = pronounceability×0.20 + memorability×0.20 + spelling_ease×0.15 + cross_language_safety×0.15 + word_segmentation×0.10 + brand_personality×0.10 + industry_fit×0.05 + novelty_score×0.05
Round to 2 decimals.

Output constraints:
- JSON array only
- same order as input
- no extra fields
- schema exactly:
[{"domain_name":"...","pronounceability":4|6|8,"memorability":4|6|8,"spelling_ease":4|6|8,"cross_language_safety":4|6|8,"word_segmentation":4|6|8,"brand_personality":4|6|8,"industry_fit":4|6|8,"novelty_score":4|6|8,"overall_linguistic_score":0.0}]"""

# Note: production pipeline currently uses deterministic linguistic scoring
# in code when enforce_deterministic_pipeline=true. This prompt is used only
# when LLM linguistic mode is explicitly enabled for experiments.


LINGUISTIC_USER = """Analyze these domains:

{domain_list}

Return JSON array only."""
