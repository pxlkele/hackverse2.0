from pydantic import BaseModel
from typing import Optional, List
from enum import Enum

class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    NEED_INFO = "need_info"

class Profile(BaseModel):
    name: str
    occupation: str
    monthly_income: Optional[float] = None
    state: str
    language: str
    has_documents: List[str] = []
    additional_context: str

class LadderStep(BaseModel):
    order: int
    action: str
    cost_rupees: float
    time_days: int
    reason: str

class Decision(BaseModel):
    scheme_id: str
    scheme_name: str
    status: EligibilityStatus
    confidence: float
    ladder: Optional[List[LadderStep]] = None
    source_doc: str
    source_span: str
    explanation: str

class TrustTrace(BaseModel):
    query_id: str
    profile: Profile
    decision: Decision
    timestamp: str
    rules_fired: List[str]
    retrieved_chunks: List[str]
