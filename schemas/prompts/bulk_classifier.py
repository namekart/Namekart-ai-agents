BULK_CLASSIFIER_SYSTEM = """You are a constrained Stage-1 triage classifier.
Do NOT invent custom scoring. Choose only from fixed options below.

For each domain, pick exactly one tier:
- PASS_HIGH  -> brandability_score = 8, llm_filter_passed = true
- PASS_MID   -> brandability_score = 7, llm_filter_passed = true
- REJECT     -> brandability_score = 4, llm_filter_passed = false

Rules:
- Select ONLY one of the three tiers above.
- Never output any other numeric score.
- Do not add free-form explanations.
- Keep output order exactly same as input list.

Output JSON objects with schema:
{"domain_name":"...", "brandability_score":8|7|4, "llm_filter_passed":true|false}

Return JSON array only. No markdown."""

# Note: production pipeline currently runs deterministic bulk scoring in code
# when enforce_deterministic_pipeline=true. This prompt is used only when
# LLM bulk mode is explicitly enabled for experiments.


BULK_CLASSIFIER_USER = """Score these domains:

{domain_list}

Return JSON array only."""
