"""CPU-only ONNX text encoder for semantic tool routing."""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from core.agent.routing.encoder import TextEncoder
from core.agent.routing.model_manifest import EmbeddingModelSpec
from core.agent.routing.model_store import artifact_path, verify_installed_model

_LOGGER = logging.getLogger(__name__)

_SESSION_LOCK = threading.Lock()
_ENCODER_CACHE: dict[str, "OnnxTextEncoder"] = {}
_ENCODER_CACHE_LOCK = threading.Lock()


class OnnxTextEncoder:
    """Lazy CPU ONNX encoder with bounded token input."""

    def __init__(self, spec: EmbeddingModelSpec) -> None:
        self._spec = spec
        self._session: ort.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None
        self._input_names: tuple[str, ...] = ()
        self._output_name: str | None = None
        self._init_lock = threading.Lock()

    @property
    def model_key(self) -> str:
        return self._spec.key

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        with self._init_lock:
            if self._session is not None:
                return
            verified, reason = verify_installed_model(self._spec)
            if not verified:
                raise FileNotFoundError(reason or "model_unavailable")
            onnx_path = artifact_path(
                self._spec,
                next(
                    artifact
                    for artifact in self._spec.files
                    if artifact.relative_path.endswith(".onnx")
                ),
            )
            tokenizer_path = artifact_path(
                self._spec,
                next(
                    artifact
                    for artifact in self._spec.files
                    if artifact.relative_path.endswith("tokenizer.json")
                ),
            )
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            self._session = ort.InferenceSession(
                str(onnx_path),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
            self._tokenizer.enable_truncation(max_length=self._spec.max_length)
            self._tokenizer.enable_padding(pad_id=0, pad_token="")
            inputs = self._session.get_inputs()
            self._input_names = tuple(item.name for item in inputs)
            outputs = self._session.get_outputs()
            self._output_name = (
                self._spec.output_name
                or (outputs[0].name if outputs else "last_hidden_state")
            )

    def _encode_batch(
        self,
        texts: Sequence[str],
        *,
        prefix: str,
    ) -> np.ndarray:
        self._ensure_loaded()
        assert self._session is not None
        assert self._tokenizer is not None

        prefixed = [f"{prefix}{text}" for text in texts]
        encodings = self._tokenizer.encode_batch(prefixed)
        input_ids = np.array([encoding.ids for encoding in encodings], dtype=np.int64)
        attention_mask = np.array(
            [encoding.attention_mask for encoding in encodings], dtype=np.int64
        )

        feed: dict[str, np.ndarray] = {}
        for name in self._input_names:
            lowered = name.lower()
            if "input_ids" in lowered or lowered == "input":
                feed[name] = input_ids
            elif "attention_mask" in lowered or "mask" in lowered:
                feed[name] = attention_mask
            elif "token_type" in lowered:
                feed[name] = np.zeros_like(input_ids)

        with _SESSION_LOCK:
            outputs = self._session.run(None, feed)
        output_index = 0
        if self._output_name:
            for index, item in enumerate(self._session.get_outputs()):
                if item.name == self._output_name:
                    output_index = index
                    break
        hidden = np.asarray(outputs[output_index], dtype=np.float32)
        pooled = _pool_embeddings(hidden, attention_mask, self._spec.pooling)
        if self._spec.normalize:
            pooled = _l2_normalize(pooled)
        _assert_finite(pooled)
        return pooled

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode_batch(texts, prefix=self._spec.query_prefix)

    def encode_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode_batch(texts, prefix=self._spec.document_prefix)


def _pool_embeddings(
    hidden: np.ndarray,
    attention_mask: np.ndarray,
    pooling: str,
) -> np.ndarray:
    if pooling == "cls":
        return hidden[:, 0, :]
    mask = attention_mask.astype(np.float32)[:, :, np.newaxis]
    summed = (hidden * mask).sum(axis=1)
    counts = np.clip(mask.sum(axis=1), 1e-9, None)
    return summed / counts


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.clip(norms, 1e-12, None)


def _assert_finite(vectors: np.ndarray) -> None:
    if not np.isfinite(vectors).all():
        raise ValueError("Encoder produced non-finite values.")


def get_onnx_encoder(spec: EmbeddingModelSpec) -> OnnxTextEncoder:
    with _ENCODER_CACHE_LOCK:
        cached = _ENCODER_CACHE.get(spec.key)
        if cached is not None:
            return cached
        encoder = OnnxTextEncoder(spec)
        _ENCODER_CACHE[spec.key] = encoder
        return encoder


def clear_encoder_cache() -> None:
    with _ENCODER_CACHE_LOCK:
        _ENCODER_CACHE.clear()
