"""Paired statistics with explicit comparison families and optional scenario clusters.

Holm applies to permutation p-values. Simultaneous intervals use Bonferroni,
not a misleading 'Holm bootstrap interval' label. Monte Carlo intervals are
estimates; synthetic template repetition does not create independent samples.
"""
from __future__ import annotations

import numpy as np


def holm(p_values):
    values = np.asarray(p_values, dtype=float)
    if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any((values < 0) | (values > 1)):
        raise ValueError('p-values must be finite and between zero and one')
    adjusted = np.empty(len(values))
    previous = 0.0
    for rank, index in enumerate(np.argsort(values, kind='stable')):
        previous = max(previous, min(1.0, float(values[index]) * (len(values) - rank)))
        adjusted[index] = previous
    return adjusted.tolist()


def paired_comparison(left, right, *, clusters=None, samples=10000, seed=20260912, family_size=1):
    a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    if a.ndim != 1 or a.shape != b.shape or not a.size or not np.all(np.isfinite(a-b)):
        raise ValueError('Paired comparison requires equal nonempty finite arrays')
    if samples < 100 or family_size < 1:
        raise ValueError('At least 100 resamples and one comparison required')
    difference = a-b
    if clusters is None:
        clusters = list(range(len(a)))
    if len(clusters) != len(a):
        raise ValueError('One cluster identity is required per pair')
    grouped = {}
    for key, value in zip(clusters, difference):
        grouped.setdefault(key, []).append(value)
    sums = np.asarray([sum(v) for v in grouped.values()])
    counts = np.asarray([len(v) for v in grouped.values()])
    n = len(sums)
    rng = np.random.default_rng(seed)
    means, extreme = [], 0
    observed = float(difference.mean())
    # Bounded working memory, including larger public datasets.
    for start in range(0, samples, 256):
        size = min(256, samples-start)
        draws = rng.integers(0, n, size=(size, n))
        means.extend((sums[draws].sum(axis=1)/counts[draws].sum(axis=1)).tolist())
        signs = rng.choice([-1, 1], size=(size, n))
        permuted = (signs*sums).sum(axis=1)/len(a)
        extreme += int(np.sum(np.abs(permuted) >= abs(observed)-1e-15))
    raw = np.quantile(means, [.025, .975]).tolist()
    simultaneous = np.quantile(means, [.025/family_size, 1-.025/family_size]).tolist()
    return {'mean_difference': observed, 'raw_ci95': raw,
            'simultaneous_ci': simultaneous, 'simultaneous_method': 'Bonferroni percentile paired cluster bootstrap',
            'family_size': family_size, 'p_value': (extreme+1)/(samples+1),
            'p_method': 'two-sided paired cluster sign permutation; plus-one Monte Carlo correction',
            'queries': len(a), 'independent_units': n, 'samples': samples, 'seed': seed}


def comparison_family(pairs, *, clusters=None, samples=10000, seed=20260912):
    rows = {name: paired_comparison(a, b, clusters=clusters, samples=samples, seed=seed,
                                    family_size=len(pairs)) for name, (a, b) in pairs.items()}
    adjusted = holm([row['p_value'] for row in rows.values()])
    for row, value in zip(rows.values(), adjusted):
        row['holm_p_value'] = value
    return rows
