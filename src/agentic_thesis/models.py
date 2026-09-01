from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class DeltaStatus(StrEnum):
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    POSSIBLY_INVALIDATED = "possibly_invalidated"
    UNKNOWN = "unknown"


class ThesisClaim(BaseModel):
    claim_id: str
    statement: str
    rationale: str
    falsifiers: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ThesisSnapshot(BaseModel):
    thesis_id: str
    company: str
    version: int
    claims: list[ThesisClaim]


class DisclosureChunk(BaseModel):
    chunk_id: str
    accession: str
    filing_date: str
    section: str
    text: str
    start_char: int
    end_char: int
    source_url: str = ""


class EvidenceItem(BaseModel):
    evidence_id: str
    chunk_id: str
    accession: str
    filing_date: str
    section: str
    source_url: str
    start_char: int
    end_char: int
    quote: str
    source_text: str
    score: float = 0.0


class EvidencePack(BaseModel):
    claim_id: str
    items: list[EvidenceItem]
    tokens_before: int
    tokens_after: int
    retained_evidence_ids: list[str]


class ClaimDelta(BaseModel):
    claim_id: str
    status: DeltaStatus
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)
    matched_falsifier: str | None = None


class ThesisDelta(BaseModel):
    base_thesis_version: int
    claim_deltas: list[ClaimDelta]


class ReviewDecision(BaseModel):
    action: Literal["approve", "reject"]
    edited_delta: ThesisDelta | None = None


class ResearchState(BaseModel):
    run_id: str
    thesis: ThesisSnapshot
    chunks: list[DisclosureChunk] = Field(default_factory=list)
    retrieved: dict[str, list[str]] = Field(default_factory=dict)
    retrieval_timings_ms: dict[str, dict[str, float]] = Field(default_factory=dict)
    evidence_packs: list[EvidencePack] = Field(default_factory=list)
    delta: ThesisDelta | None = None
    review: ReviewDecision | None = None
    timings_ms: dict[str, float] = Field(default_factory=dict)
    status: str = "running"
    error: str | None = None
