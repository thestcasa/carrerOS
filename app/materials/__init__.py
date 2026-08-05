"""Deterministic, provenance-preserving application material services."""

from app.materials.contracts import (
    AnswerPrompt,
    ApprovedAnswerFact,
    ApprovedFact,
    Claim,
    GeneratedAnswer,
    GeneratedDocument,
    GenerationRequest,
    GenerationResult,
    JobTarget,
)
from app.materials.generation import DeterministicMaterialGenerator
from app.materials.review import IndependentMaterialReviewer
from app.materials.storage import DraftArtifactStore, DraftVersionExistsError
from app.materials.validation import MaterialValidator

__all__ = [
    "AnswerPrompt",
    "ApprovedAnswerFact",
    "ApprovedFact",
    "Claim",
    "DeterministicMaterialGenerator",
    "DraftArtifactStore",
    "DraftVersionExistsError",
    "GeneratedAnswer",
    "GeneratedDocument",
    "GenerationRequest",
    "GenerationResult",
    "IndependentMaterialReviewer",
    "JobTarget",
    "MaterialValidator",
]
