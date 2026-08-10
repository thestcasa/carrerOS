from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from app.applications import ApplicationService
from app.materials.contracts import MaterialAgentProvenance
from app.materials.generation import DeterministicMaterialGenerator
from app.materials.review import IndependentMaterialReviewer


class _UnidentifiedGenerator:
    pass


class _IdentifiedGenerator:
    provenance = MaterialAgentProvenance(
        agent_version="custom-generator-v3",
        model_version="custom-model-v7",
        prompt_version="custom-prompt-v2",
    )


def _service(
    tmp_path: Path,
    document_generation_agent: Any | None = None,
) -> ApplicationService:
    return ApplicationService(
        cast(Any, object()),
        cast(Any, object()),
        tmp_path,
        document_generation_agent=document_generation_agent,
    )


def test_rejects_injected_material_agent_without_provenance(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="document generation agent must declare"):
        _service(tmp_path, _UnidentifiedGenerator())


def test_records_declared_material_agent_provenance(tmp_path: Path) -> None:
    service = _service(tmp_path, _IdentifiedGenerator())

    assert service._generator_provenance == _IdentifiedGenerator.provenance
    assert service._reviewer_provenance == IndependentMaterialReviewer.provenance
    assert DeterministicMaterialGenerator.provenance.model_version == "deterministic-material-v2"
