"""Pinned embedding model manifests for tool routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    relative_path: str
    byte_size: int
    sha256: str

    @property
    def source_url(self) -> str:
        return ""  # populated by spec method


@dataclass(frozen=True, slots=True)
class EmbeddingModelSpec:
    key: str
    repository: str
    revision: str
    license_id: str
    files: tuple[ModelArtifact, ...]
    max_length: int
    pooling: Literal["mean", "cls"]
    normalize: bool
    query_prefix: str
    document_prefix: str
    output_name: str | None = None

    def artifact_url(self, artifact: ModelArtifact) -> str:
        return (
            f"https://huggingface.co/{self.repository}/resolve/"
            f"{self.revision}/{artifact.relative_path}"
        )

    @property
    def total_bytes(self) -> int:
        return sum(file.byte_size for file in self.files)


# SHA-256 values are verified at install time; sizes from HuggingFace metadata.
_MINILM_FILES = (
    ModelArtifact(
        relative_path="onnx/model_qint8_avx512_vnni.onnx",
        byte_size=23_026_053,
        sha256="4278337fd0ff3c68bfb6291042cad8ab363e1d9fbc43dcb499fe91c871902474",
    ),
    ModelArtifact(
        relative_path="tokenizer.json",
        byte_size=466247,
        sha256="be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    ),
    ModelArtifact(
        relative_path="config.json",
        byte_size=612,
        sha256="953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41",
    ),
)

_BGE_FILES = (
    ModelArtifact(
        relative_path="onnx/model_qint8_avx512_vnni.onnx",
        byte_size=34118638,
        sha256="c7663636f9d9d2660b1e5eb5ac3432109fa27a70d89a548dae8beae7b661890b",
    ),
    ModelArtifact(
        relative_path="tokenizer.json",
        byte_size=711396,
        sha256="d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
    ),
    ModelArtifact(
        relative_path="config.json",
        byte_size=743,
        sha256="",
    ),
)

CANDIDATE_MODEL_SPECS: dict[str, EmbeddingModelSpec] = {
    "all-minilm-l6-v2": EmbeddingModelSpec(
        key="all-minilm-l6-v2",
        repository="sentence-transformers/all-MiniLM-L6-v2",
        revision="d83dd3760b5bfe921f2fe125446b17bf0b7eda8c",
        license_id="apache-2.0",
        files=_MINILM_FILES,
        max_length=256,
        pooling="mean",
        normalize=True,
        query_prefix="",
        document_prefix="",
        output_name=None,
    ),
    "bge-small-en-v1.5": EmbeddingModelSpec(
        key="bge-small-en-v1.5",
        repository="BAAI/bge-small-en-v1.5",
        revision="07e27b8edc19a66f020db6906126054f190f7284",
        license_id="mit",
        files=_BGE_FILES,
        max_length=256,
        pooling="cls",
        normalize=True,
        query_prefix="Represent this sentence for searching relevant passages: ",
        document_prefix="",
        output_name=None,
    ),
}

# Production model selected after benchmark; default until benchmark runs.
PRODUCTION_MODEL_KEY = "all-minilm-l6-v2"

PRODUCTION_MODEL_SPEC: EmbeddingModelSpec = CANDIDATE_MODEL_SPECS[PRODUCTION_MODEL_KEY]


def get_model_spec(key: str) -> EmbeddingModelSpec | None:
    return CANDIDATE_MODEL_SPECS.get(key)
