from pydantic import BaseModel
from typing import Literal

class DomainDecision(BaseModel):
    domain_name: str
    decision: Literal["STRONG_BUY", "BUY", "MAYBE", "SKIP"]

class ValuationReport(BaseModel):
    batch_id: str
    strong_buy: list[DomainDecision]
    buy: list[DomainDecision]
    maybe: list[DomainDecision]
    skip: list[DomainDecision]
