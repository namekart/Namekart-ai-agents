from pydantic import BaseModel, Field, model_validator


class LinguisticReport(BaseModel):
    domain_name: str
    pronounceability: int = Field(ge=1, le=10)
    memorability: int = Field(ge=1, le=10)
    spelling_ease: int = Field(ge=1, le=10)
    cross_language_safety: int = Field(ge=1, le=10)
    word_segmentation: int = Field(ge=1, le=10)
    brand_personality: int = Field(ge=1, le=10)
    industry_fit: int = Field(ge=1, le=10)
    novelty_score: int = Field(ge=1, le=10)
    overall_linguistic_score: float = 0.0

    @model_validator(mode="after")
    def compute_overall_linguistic_score(self) -> "LinguisticReport":
        self.overall_linguistic_score = round(
            self.pronounceability * 0.20
            + self.memorability * 0.20
            + self.spelling_ease * 0.15
            + self.cross_language_safety * 0.15
            + self.word_segmentation * 0.10
            + self.brand_personality * 0.10
            + self.industry_fit * 0.05
            + self.novelty_score * 0.05,
            2,
        )
        return self
