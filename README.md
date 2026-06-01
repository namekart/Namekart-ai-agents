# Namekart AI Agents Pipeline

This project is an advanced, multi-agent AI pipeline designed to evaluate domain names for investment and acquisition (buy/skip decisions). It processes seed domains through four distinct agents:
1. **Bulk Classifier**: Filters out unbrandable/junk domains.
2. **Linguistic Agent**: Evaluates pronunciation, memorability, spelling ease, and cross-language safety.
3. **Market Agent**: Gathers web search data (Tavily) to synthesize market existence, trajectory, and funding activity.
4. **Valuation Agent**: Combines the linguistic and market reports with pricing data to make final `STRONG_BUY`, `BUY`, `MAYBE`, or `SKIP` decisions.

---

## 🏗️ Architecture & Optimizations

This pipeline has been heavily optimized for **API rate limits**, **token cost efficiency**, and **high throughput**:

- **Strict Batching**: The Linguistic and Market agents do *not* make 1 LLM call per domain. They batch domains (e.g., 10 per call for Linguistic, 5 for Market), reducing total LLM API calls by ~87%.
- **Progressive Filtering (Gating)**: If a domain scores poorly on the Linguistic evaluation (default `< 5.0`), the pipeline skips the Market Agent entirely. This saves expensive search queries and massive LLM tokens for domains that will never be a "Buy".
- **Throttling & Resiliency**: The pipeline runs sequentially with configurable delays (`request_delay_seconds`) to stay under rate limits. The OpenAI SDK is configured to automatically retry `429` (Rate Limit) and `5xx` errors with exponential backoff.
- **Deterministic Fallbacks**: If the API completely fails or exhausts all retries, agents instantly fallback to deterministic heuristics. The pipeline will *never* crash due to rate limits.
- **Token Compression**: All system prompts are highly compressed, saving ~44% tokens per pipeline run.

---

## ⚙️ Configuration (.env)

You can control the pipeline's aggression and cost via the following variables in `.env` (loaded by `app/config.py`):

```env
# Models
MODEL_FAST=anthropic/claude-3-haiku-20240307   # Used for bulk & linguistic (cheap/fast)
MODEL_PRO=anthropic/claude-3-opus-20240229     # Used for market & valuation (reasoning)

# Pipeline Throttling (Tune these based on your API Tier)
MAX_CONCURRENT_DOMAINS=2       # Not heavily used now that we batch, but controls thread pools if used
REQUEST_DELAY_SECONDS=2.0      # Pause between API calls (Increase if you hit 429s)
MAX_API_RETRIES=5              # Exponential backoff retries for LLM calls

# Progressive Filtering
LINGUISTIC_GATE_THRESHOLD=5.0  # Min linguistic score required to trigger Market Research

# Batching Settings
LINGUISTIC_BATCH_SIZE=10       # Domains per LLM call (pure text)
MARKET_BATCH_SIZE=5            # Domains per LLM call (includes heavy search text)
MAX_SEARCH_CONTENT_CHARS=300   # Truncates Tavily text to save tokens
```

---

## 🚀 What to do next (Moving to Production)

1. **Upgrade your API Plan**: 
   - Currently, the OpenRouter Free Tier has a hard limit of `50 requests / day` and very low RPM (requests per minute). 
   - To process hundreds of domains, you MUST move to a paid OpenRouter tier, or use direct API keys from Anthropic/Google/OpenAI. 
2. **Tune the Delay**:
   - Once on a paid tier, change `REQUEST_DELAY_SECONDS` from `2.0` down to `0.5` or `0.0`. The pipeline will execute lightning fast.
3. **Increase Batch Sizes (Optional)**:
   - If using models with massive context windows (like Gemini 1.5 Pro or Claude 3.5 Sonnet), you can increase `LINGUISTIC_BATCH_SIZE` to 20 or 30 to save even more API calls.
4. **Connect Production Database**:
   - Change `DATA_SOURCE` in `.env` from `file` to `prod` to switch from the local `seed_domains.csv` to your Java backend's PostgreSQL database. Ensure `DB_URL_PROD` is correctly set.

---

## ⚠️ Points to Remember

- **Gated / Skipped Domains**: Domains that fail the `LINGUISTIC_GATE_THRESHOLD` do not disappear. They are safely recorded in the database / CSV output as a `SKIP` decision with their final score matching their linguistic score.
- **Heuristic Fallbacks**: If you look at your results and see domains with a `linguistic_score` of exactly `7.0` and a `novelty_score` of `6`, or a `bulk_classifier` reason of `"fallback heuristic"`, **it means you hit an API rate limit that exhausted all retries**. Upgrade your API key credits to get real AI evaluations.
- **Tavily Credits**: The Market Agent consumes 3-4 Tavily search credits *per promising domain*. Keep an eye on your Tavily usage dashboard.
- **Prompt Edits**: If you ever edit the prompts in `prompts/`, remember to keep them dense. Use symbols (`|`, `→`, `≥`) and eliminate conversational fluff. Every token saved in a system prompt is multiplied by thousands of runs.
