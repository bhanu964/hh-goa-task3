"""Face comparison maths and thresholding.

These tests use synthetic vectors so they run without model weights; the real
model is exercised by the live pipeline and by tests/test_search_live.py.
"""

import numpy as np
import pytest

from face.matcher import FaceMatch, compare, cosine_similarity


def unit(vector):
    v = np.asarray(vector, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_identical_vectors_score_one():
    v = unit([1.0, 2.0, 3.0])
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_opposite_vectors_score_minus_one():
    v = unit([1.0, 0.0, 0.0])
    assert cosine_similarity(v, -v) == pytest.approx(-1.0)


def test_orthogonal_vectors_score_zero():
    assert cosine_similarity(unit([1.0, 0.0]), unit([0.0, 1.0])) == pytest.approx(0.0)


def test_similarity_is_symmetric():
    a, b = unit([1.0, 2.0, 3.0]), unit([3.0, 1.0, 2.0])
    assert cosine_similarity(a, b) == pytest.approx(cosine_similarity(b, a))


def test_similarity_is_scale_invariant():
    a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert cosine_similarity(a, a * 7.0) == pytest.approx(1.0)


def test_result_stays_inside_valid_range():
    rng = np.random.default_rng(0)
    for _ in range(200):
        a, b = unit(rng.normal(size=64)), unit(rng.normal(size=64))
        assert -1.0 <= cosine_similarity(a, b) <= 1.0


def test_dimension_mismatch_is_rejected():
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_similarity(np.ones(512), np.ones(128))


def test_zero_vector_is_rejected():
    with pytest.raises(ValueError, match="zero-length"):
        cosine_similarity(np.zeros(8), np.ones(8))


def test_match_requires_reaching_the_threshold():
    assert compare(unit([1.0, 0.0]), unit([1.0, 0.0]), threshold=0.45).is_match


def test_below_threshold_is_not_a_match():
    assert not compare(unit([1.0, 0.0]), unit([0.0, 1.0]), threshold=0.45).is_match


def test_threshold_boundary_is_inclusive():
    assert FaceMatch(similarity=0.45, threshold=0.45).is_match
    assert not FaceMatch(similarity=0.4499, threshold=0.45).is_match


def test_percent_maps_the_full_range_onto_zero_to_hundred():
    assert FaceMatch(1.0, 0.45).percent == pytest.approx(100.0)
    assert FaceMatch(0.0, 0.45).percent == pytest.approx(50.0)
    assert FaceMatch(-1.0, 0.45).percent == pytest.approx(0.0)


def test_a_stricter_threshold_can_reject_the_same_score():
    a, b = unit([1.0, 0.0]), unit([1.0, 1.0])  # cosine ~0.707
    assert compare(a, b, threshold=0.45).is_match
    assert not compare(a, b, threshold=0.9).is_match
