from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class DeltaStatus(StrEnum):
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    POSSIBLY_INVALIDATED = "possibly_invalidated"
    UNKNOWN = "unknown"


class RunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMMITTED = "committed"
    REJECTED = "rejected"
    FAILED = "failed"
    VERSION_CONFLICT = "version_conflict"
    INVALID_REVIEW = "invalid_review"


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


class CitationSpan(BaseModel):
    span_id: str
    kind: Literal["sentence", "list_item", "table_row"]
    text: str
    start_char: int
    end_char: int


class DisclosureChunk(BaseModel):
    chunk_id: str
    accession: str
    filing_date: str
    section: str
    text: str
    start_char: int
    end_char: int
    source_url: str = ""
    citation_spans: list[CitationSpan] = Field(default_factory=list)


class DisclosureDocument(BaseModel):
    document_id: str = Field(min_length=1, max_length=200)
    thesis_id: str = Field(min_length=1, max_length=200)
    accession: str = Field(min_length=1, max_length=200)
    filing_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_url: str = ""
    content: str = Field(min_length=1, max_length=10_000_000)


class DisclosureSummary(BaseModel):
    document_id: str
    thesis_id: str
    accession: str
    filing_date: str
    source_url: str = ""


class EvidenceItem(BaseModel):
    evidence_id: str
    chunk_id: str
    accession: str
    filing_date: str
    section: str
    kind: Literal["sentence", "list_item", "table_row"]
    source_url: str
    start_char: int
    end_char: int
    source_start_char: int
    source_end_char: int
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


class RunSummary(BaseModel):
    run_id: str
    thesis_id: str
    disclosure_id: str
    base_thesis_version: int
    status: RunStatus
    committed_thesis_version: int | None = None
    error: str | None = None


class ThesisRun(RunSummary):
    thesis: ThesisSnapshot
    delta: ThesisDelta | None = None
    evidence_packs: list[EvidencePack] = Field(default_factory=list)
    review: ReviewDecision | None = None
    timings_ms: dict[str, float] = Field(default_factory=dict)
    retrieval_timings_ms: dict[str, dict[str, float | bool]] = Field(
        default_factory=dict
    )


class ThesisRevision(BaseModel):
    run_id: str
    thesis_id: str
    disclosure_id: str
    base_thesis_version: int
    committed_thesis_version: int
    delta: ThesisDelta
    evidence_packs: list[EvidencePack]
    review: ReviewDecision


class SecMonitor(BaseModel):
    thesis_id: str
    cik: str
    forms: list[str]
    enabled: bool
    last_accession: str | None = None
    last_checked_at: str | None = None
    last_error: str | None = None
    last_imported: int = 0


class ResearchState(BaseModel):
    run_id: str
    disclosure_id: str
    thesis: ThesisSnapshot
    chunks: list[DisclosureChunk] = Field(default_factory=list)
    retrieved: dict[str, list[str]] = Field(default_factory=dict)
    retrieval_timings_ms: dict[str, dict[str, float | bool]] = Field(default_factory=dict)
    evidence_packs: list[EvidencePack] = Field(default_factory=list)
    delta: ThesisDelta | None = None
    review: ReviewDecision | None = None
    timings_ms: dict[str, float] = Field(default_factory=dict)
    status: str = "running"
    error: str | None = None
