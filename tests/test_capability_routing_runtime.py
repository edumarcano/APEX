"""Regression coverage for ONNX encoder pooling and normalization helpers."""

from __future__ import annotations

import unittest

import numpy as np

from core.agent.routing.onnx_encoder import _assert_finite, _l2_normalize, _pool_embeddings


class CapabilityRoutingRuntimeTests(unittest.TestCase):
    def test_mean_pooling_respects_attention_mask(self) -> None:
        hidden = np.array(
            [
                [
                    [1.0, 0.0],
                    [9.0, 9.0],
                    [3.0, 3.0],
                ]
            ],
            dtype=np.float32,
        )
        attention_mask = np.array([[1, 1, 0]], dtype=np.int64)
        pooled = _pool_embeddings(hidden, attention_mask, "mean")
        np.testing.assert_allclose(pooled, np.array([[5.0, 4.5]], dtype=np.float32))

    def test_cls_pooling_returns_first_token(self) -> None:
        hidden = np.array([[[2.0, 4.0], [8.0, 16.0]]], dtype=np.float32)
        attention_mask = np.array([[1, 1]], dtype=np.int64)
        pooled = _pool_embeddings(hidden, attention_mask, "cls")
        np.testing.assert_allclose(pooled, np.array([[2.0, 4.0]], dtype=np.float32))

    def test_l2_normalize_produces_unit_vectors(self) -> None:
        vectors = np.array([[3.0, 4.0], [0.0, 2.0]], dtype=np.float32)
        normalized = _l2_normalize(vectors)
        norms = np.linalg.norm(normalized, axis=1)
        np.testing.assert_allclose(norms, np.array([1.0, 1.0], dtype=np.float32))

    def test_finite_check_rejects_nan_values(self) -> None:
        with self.assertRaises(ValueError):
            _assert_finite(np.array([[np.nan, 1.0]], dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
