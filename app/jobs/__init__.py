"""Deterministic job classification and candidate-configured scoring."""

from app.jobs.scoring import (
    JobEvaluation,
    NormalizedJob,
    RoleClassification,
    evaluate_job,
)

__all__ = ["JobEvaluation", "NormalizedJob", "RoleClassification", "evaluate_job"]
