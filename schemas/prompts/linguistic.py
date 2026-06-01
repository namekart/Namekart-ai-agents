LINGUISTIC_SYSTEM = """You are a constrained Stage-2 linguistic scorer.
Do NOT invent arbitrary scores. Use only fixed score buckets.

Allowed score values for every dimension:
- 4 = weak
- 6 = medium
- 8 = strong

Dimensions:
- pronounceability
- memorability
- spelling_ease
- cross_language_safety
- word_segmentation
- brand_personality
- industry_fit
- novelty_score

Rules:
- Every dimension must be exactly one of {4, 6, 8}.
- No other values allowed.
- Do not output explanations.
- Keep output order exactly same as input list.

Compute overall_linguistic_score using:
overall_linguistic_score = pronounceability×0.20 + memorability×0.20 + spelling_ease×0.15 + cross_language_safety×0.15 + word_segmentation×0.10 + brand_personality×0.10 + industry_fit×0.05 + novelty_score×0.05
Round to 2 decimals.

Return JSON array only:
[{"domain_name":"...","pronounceability":8,"memorability":6,"spelling_ease":8,"cross_language_safety":8,"word_segmentation":6,"brand_personality":6,"industry_fit":4,"novelty_score":6,"overall_linguistic_score":6.85}]"""

# Note: production pipeline currently uses deterministic linguistic scoring
# in code when enforce_deterministic_pipeline=true. This prompt is used only
# when LLM linguistic mode is explicitly enabled for experiments.


LINGUISTIC_USER = """Analyze these domains:

{domain_list}

Return JSON array only."""
