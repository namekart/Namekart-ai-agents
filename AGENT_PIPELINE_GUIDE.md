# Namekart Agents and Pipeline Guide

This document explains:

- Bulk classifier agent: input, output, rules, and scoring
- Linguistic agent: input, output, rules, and scoring
- End-to-end pipeline flow and generated CSV outputs
- Deterministic behavior and key config parameters

---

## 1) System Overview

The current pipeline is a two-agent deterministic system:

1. **Bulk classifier (Stage 1)**: coarse triage, removes obvious low-quality domains.
2. **Linguistic agent (Stage 2)**: deep language-quality scoring and gate pass/fail.

After both stages, candidates are ranked and labeled with decisions:

- `STRONG_BUY`
- `BUY`
- `MAYBE`
- `SKIP`

---

## 2) Determinism (Same Input => Same Output)

The pipeline is configured to be deterministic by default:

- `enforce_deterministic_pipeline = true`
- `use_llm_bulk_classifier = false`
- `use_llm_linguistic = false`

When deterministic mode is on, bulk and linguistic LLM paths are ignored, even if toggled elsewhere.

---

## 3) Bulk Classifier Agent (Stage 1)

### Input

- `list[str]` domains (e.g., `["therapist.com", "growhub.net", ...]`)

### Output

For each domain, a `BulkFilterResult`:

- `domain_name: str`
- `brandability_score: int` (1–10)
- `llm_filter_passed: bool`
- `llm_filter_reason: str` (kept empty in current compact pipeline output)

### Processing Steps

1. Parse domain into features:
   - stem, tld, length, vowel ratio, digits, dash, consonant runs, junk patterns, etc.
2. Apply hard reject checks (instant fail).
3. If not hard-rejected, compute brandability score (1–10).
4. Pass if `score >= bulk_filter_pass_score` (default: `8`).

### Hard Reject Checks

A domain is rejected immediately if any check hits:

- Blocked TLD (for example: `xyz`, `top`, `click`, `win`, `vip`, ...)
- Weak TLD blocked (if enabled)
- Not in TLD allowlist (if allowlist is set)
- Stem shorter than minimum length
- Stem longer than maximum length
- Digits present (if enabled)
- Dash present (if enabled)
- Junk pattern:
  - keyboard mash pattern
  - repeated characters
  - consonant-only random pattern
  - single-char segment pattern (`a-b-c-d`)
- Long consonant cluster
- Extreme vowel ratio (too low or too high)
- Hyper keyword / geo keyword pattern (if enabled)

### Brandability Score Formula (Deterministic Heuristic)

Initial score: `4`

Adjustments:

- **Length**
  - `+3` if stem length is `5..8`
  - `+1` if length is `4` or `9..10`
  - `-1` if longer but still moderate
  - `-3` if very long
- **Vowel balance**
  - `+2` if ratio in ideal range
  - `+1` if acceptable range
  - `-1` if awkward ratio
- **Consonant run**
  - `-2` if run `>= 3`
  - `-1` in a mild long-run case
- **Vowel cluster**
  - `-1` if present
- **TLD quality**
  - premium tld: `+2`
  - strong tld: `+1`
  - weak tld: `-2`
- **Brand signal**
  - `+1` if power word exists
  - `+1` if recognizable word root exists
- **Generic short dictionary stem**
  - `-1`

Final score is clamped to `1..10`.

Pass rule:

- `llm_filter_passed = (brandability_score >= bulk_filter_pass_score)`

---

## 4) Linguistic Agent (Stage 2)

### Input

- Only domains that passed bulk stage.

### Output

For each input domain, `LinguisticReport`:

- `pronounceability` (1–10)
- `memorability` (1–10)
- `spelling_ease` (1–10)
- `cross_language_safety` (1–10)
- `word_segmentation` (1–10)
- `brand_personality` (1–10)
- `industry_fit` (1–10)
- `novelty_score` (1–10)
- `overall_linguistic_score` (weighted, rounded to 2 decimals)

### Dimension Scoring

All dimensions are computed from deterministic rules over the domain stem:

- vowel ratio
- consonant runs / clusters
- presence of digits/dashes
- known word roots / power words
- known unsafe stem patterns
- common suffix/prefix cliches
- short coined-name characteristics

Special handling exists for low-quality junk patterns and some `.ai` coined suffix patterns.

### Weighted Overall Formula

```
overall_linguistic_score =
  pronounceability * 0.20
  + memorability * 0.20
  + spelling_ease * 0.15
  + cross_language_safety * 0.15
  + word_segmentation * 0.10
  + brand_personality * 0.10
  + industry_fit * 0.05
  + novelty_score * 0.05
```

Rounded to 2 decimal places.

### TLD Adjustment for Gate

Adjusted score is computed before gate checks:

- premium TLD: `+0.0`
- `ai`: `+0.0`
- strong TLD: `-0.2`
- weak TLD: `-1.0`
- blocked TLD: `-3.0`
- others: `-0.8`

### Linguistic Gate Rules

A domain passes gate only if all required checks pass:

- not blocked/weak TLD (as configured)
- adjusted overall >= threshold
- minimum pronounceability
- minimum memorability
- minimum spelling ease
- minimum brand signal (`max(word_segmentation, brand_personality)`), with controlled keyword exception
- minimum weakest dimension floor, with controlled keyword exception

Current gate defaults are strict quality settings (see config section below).

---

## 5) End-to-End Pipeline Flow

### Step-by-step flow

1. **Load input domains**
   - from `seed_domains.csv` (file mode), or
   - from DB table `shortlisted_master_data_acqes_new` by `process_date` (prod/temp)
2. **Bulk classifier stage**
   - evaluates all input domains
   - outputs pass/fail + score
3. **Bulk LLM batching (only if LLM bulk mode is enabled)**
   - domains are grouped by `bulk_llm_batch_size` (default `500`) per bulk LLM call
   - this reduces API call count and billing overhead
4. **Pipeline batching after bulk**
   - bulk-passed domains are split by `pipeline_batch_size` (default `500`)
   - this is the batching Claude should describe as "after bulk classifier"
5. **Linguistic sub-batching (only if linguistic LLM mode is enabled)**
   - each pipeline batch is split by `linguistic_batch_size` (default `10`) for linguistic LLM calls
4. **Linguistic stage**
   - computes 8 dimensions + overall score
   - applies gate pass/fail
6. **Ranking and decision assignment**
   - combines linguistic score + valuation display score
   - assigns `STRONG_BUY/BUY/MAYBE/SKIP`
7. **CSV/DB output**
   - writes reports for audit and shortlist views

### Important batching note

There are **two different batching concepts**:

1. **Bulk-call batching** (`bulk_llm_batch_size`)  
   Used only when bulk LLM mode is active.

2. **Post-bulk pipeline batching** (`pipeline_batch_size`)  
   Always used to process bulk-passed domains through downstream stages.

---

## 6) Output CSV Files

Using:

```bash
uv run python scripts/export_pipeline_csvs.py
```

the pipeline exports:

1. `data/all_domains_report.csv`
   - all input domains
   - bulk and linguistic pass/fail and stage outcomes
2. `data/bulk_shortlisted.csv`
   - bulk pass list
3. `data/linguistic_shortlisted.csv`
   - linguistic pass list
4. `data/pipeline_results.csv`
   - full ranked decision output for bulk-passed domains

---

## 7) Decision Assignment (Final Labels)

Decisions are assigned from final candidate rows:

- Gate fail => `SKIP`
- High linguistic + sufficient bulk => `STRONG_BUY`
- Mid-high linguistic + sufficient bulk => `BUY`
- Lower passing range => `MAYBE`
- Otherwise => `SKIP`

These thresholds are implemented in `agents/scoring.py`.

---

## 8) Key Config Parameters

Located in `app/config.py`.

### Input/pipeline

- `data_source`
- `pipeline_process_date`
- `pipeline_batch_size`
- `bulk_llm_batch_size`

### Bulk stage

- `bulk_filter_pass_score`
- `bulk_min_stem_length`
- `bulk_max_stem_length`
- `bulk_reject_digits`
- `bulk_reject_dashes`
- `bulk_reject_hyper_keywords`
- `bulk_reject_geo_keywords`
- `bulk_block_weak_tlds`
- `bulk_allowed_tlds`

### Linguistic gate

- `linguistic_gate_threshold`
- `linguistic_min_pronounceability`
- `linguistic_min_memorability`
- `linguistic_min_spelling_ease`
- `linguistic_min_dimension_score`
- `linguistic_min_brand_signal`
- `linguistic_min_industry_fit`
- `linguistic_block_weak_tlds`

### Determinism

- `enforce_deterministic_pipeline` (recommended `true`)
- `use_llm_bulk_classifier`
- `use_llm_linguistic`

---

## 9) Practical Run Commands

### Full export (recommended for testing)

```bash
uv run python scripts/export_pipeline_csvs.py
```

### Specific process date

```bash
uv run python scripts/export_pipeline_csvs.py --date 2026-05-20
```

### Quick smoke test

```bash
uv run python scripts/export_pipeline_csvs.py --limit 500
```

---

## 10) Notes

- Prompt files exist for optional experiment modes, but deterministic mode is the production path.
- Bulk reason text is intentionally compact/empty in pipeline artifacts to reduce noise and cost.
- Linguistic stage does not consume bulk descriptive text; it scores domain names independently.

---

## 11) Claude Prompt Template (Batching-Correct Report)

Use this prompt with Claude when you want a report that correctly explains batching order:

```text
Write a clear technical report of the Namekart two-agent pipeline.

Mandatory correctness requirements:
1) Explain two batching layers separately:
   - bulk_llm_batch_size (default 500): used only for bulk LLM calls when LLM bulk mode is enabled.
   - pipeline_batch_size (default 500): applied AFTER bulk pass filtering to process downstream stages.
2) Mention linguistic_batch_size (default 10) as sub-batching only when linguistic LLM mode is enabled.
3) State that deterministic mode can bypass LLM paths:
   - enforce_deterministic_pipeline=true forces deterministic bulk + linguistic scoring.
4) Keep stage order exactly:
   input load -> bulk classifier -> post-bulk pipeline batching -> linguistic scoring + gate -> ranking/decision -> CSV outputs.
5) Include output files:
   - data/all_domains_report.csv
   - data/bulk_shortlisted.csv
   - data/linguistic_shortlisted.csv
   - data/pipeline_results.csv

Do not merge the two batching concepts into one sentence.
```

