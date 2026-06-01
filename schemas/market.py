from pydantic import BaseModel
from typing import Literal

class MarketResearchReport(BaseModel):
    domain_name: str
    market_exists: bool
    market_trajectory: Literal["growing", "stable", "declining", "unknown"]
    cagr_estimate: str               # e.g. "12–18%"
    funding_activity: str            # e.g. "high — 3 recent Series B in space"
    demand_signals: str              # 1 sentence summary
    needs_manual_review: bool = False
    raw_search_summary: str          # condensed summary of what searches returned
