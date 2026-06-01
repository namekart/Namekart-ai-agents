"""
APRResult schema — output of the APR-Prediction-Agent bridge.

Maps the APR agent's JSON output into a typed structure that feeds
directly into the namekart valuation + decision pipeline.
"""
from typing import Literal
from pydantic import BaseModel, Field


class APRResult(BaseModel):
    """Structured output from the APR-Prediction-Agent for one domain."""

    domain_name: str

    # ── Price prediction ──────────────────────────────────────────────
    predicted_apr: float = Field(
        default=0.0,
        description="Parsed numeric value of predictedAPR (e.g. '$1,250' → 1250.0)",
    )
    apr_range_low: float = Field(default=0.0)
    apr_range_high: float = Field(default=0.0)
    confidence: Literal["High", "Medium", "Low"] = "Low"

    # ── Domain intelligence ───────────────────────────────────────────
    domain_category: str = Field(
        default="Generic",
        description="Category from APR domain_analysis_node: Brandable/Descriptive/etc.",
    )
    domain_description: str = Field(default="")

    # ── Comparable search ─────────────────────────────────────────────
    similar_domains_count: int = Field(
        default=0,
        description="Number of comparable historical domains found in ChromaDB.",
    )

    # ── Derived market signals (used by valuation_agent) ─────────────
    market_trajectory: Literal["growing", "stable", "declining", "unknown"] = "unknown"
    market_exists: bool = False
    needs_manual_review: bool = False

    # ── Reasoning summary ─────────────────────────────────────────────
    reasoning_summary: str = Field(default="", max_length=500)

    # ── Source metadata ───────────────────────────────────────────────
    source: Literal["apr_agent", "market_agent_fallback"] = "apr_agent"
    error: str = Field(default="")
