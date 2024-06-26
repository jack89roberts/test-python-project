"""
Test functions for the PARC score (src/locomoset/metrics/parc.py).
"""
from __future__ import annotations

import numpy as np
import pytest

from locomoset.metrics.parc import PARCMetric, _feature_reduce, _lower_tri_arr


def test_parc_class_perfect_features(dummy_features_perfect, dummy_labels, test_seed):
    """Test PARC metric class for perfect features"""
    metric = PARCMetric(random_state=test_seed, feat_red_dim=None, scale_features=False)
    assert metric.metric_name == "parc"
    assert metric.inference_type == "features"
    assert metric.dataset_dependent is True
    assert metric.fit_metric(dummy_features_perfect, dummy_labels) == pytest.approx(100)


def test_parc_class_random_features(dummy_features_random, dummy_labels, test_seed):
    """Test PARC metric class for random features"""
    metric = PARCMetric(random_state=test_seed, feat_red_dim=None, scale_features=False)
    assert metric.metric_name == "parc"
    assert metric.inference_type == "features"
    assert metric.dataset_dependent is True
    assert metric.fit_metric(dummy_features_random, dummy_labels) == pytest.approx(
        0.0, abs=0.2
    )


def test_lower_tri():
    """
    Test that the lower triangular values (offset from diag by one) values of a square
    matrix are being correctly pulled out.

    NB: This actually pulls out the upper triangular values but applies to a symmetric
    matrix by definition.
    """
    n = 5

    # create n^2 array of numbers from 1 -> 25
    arr = np.array([i + 1 for i in range(n**2)]).reshape((n, n))

    # analytical sum of upper triangular values for above matrix
    s = (n**2 * (n**2 + 1)) / 2 - sum(
        [(k * (k * (2 * n + 1) - 2 * n + 1)) / 2 for k in range(1, n + 1)]
    )

    assert s == sum(_lower_tri_arr(arr))


def test_feature_reduce(dummy_features_random, test_seed, rng, test_n_samples):
    """
    Test that the feature reduction method:
        - returns the features if f = None is given
        - raises an exception if f > min(features.shape)
        - returns the features with the correct shape if f < min(features.shape)
    """
    assert np.all(_feature_reduce(dummy_features_random, test_seed, None)) == np.all(
        dummy_features_random
    )

    with pytest.raises(ValueError):
        _feature_reduce(dummy_features_random, test_seed, 10000)

    large_n_features = 100
    features = rng.normal(size=(test_n_samples, large_n_features))
    red_dim = 32
    red_features = _feature_reduce(features, test_seed, f=red_dim)
    assert red_features.shape == (test_n_samples, red_dim)
