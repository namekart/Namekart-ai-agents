from sqlalchemy import Column, String, Date, Float, Boolean, Integer, Text, DateTime
from sqlalchemy.orm import declarative_base
import datetime

Base = declarative_base()

class ShortlistedMasterDataAcqes(Base):
    __tablename__ = "shortlisted_master_data_acqes_new"

    domain = Column(String(255), primary_key=True)
    process_date = Column(Date)
    auction_price = Column(Float)
    is_shortlisted = Column(Integer, nullable=True) # Assuming filtering equivalent
    shortlist_status = Column(String(50), nullable=True)     # assuming text reason/status
    gdv = Column(Float, nullable=True)              # Brandability / metric score equivalent

class AgentEvaluationResult(Base):
    __tablename__ = 'agent_evaluation_results'

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain_name = Column(String(255))
    decision = Column(String(50))
    thesis = Column(Text, nullable=True)
    linguistic_score = Column(Float, nullable=True)
    market_score = Column(Float, nullable=True)
    valuation_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
