from pydantic import BaseModel

class BulkFilterResult(BaseModel):
    domain_name: str
    brandability_score: int          # 1–10
    llm_filter_passed: bool
    llm_filter_reason: str = ""
