import os
import pytest


def test_semantic_ranks_paraphrase_above_unrelated_text():
    from chronoverse.semantic import score_texts
    try:
        scores = score_texts('Who leads the company?', ['The chief executive is Mira Chen.', 'Rainfall reached thirty millimeters overnight.'])
    except RuntimeError as exc:
        pytest.skip(f'Optional local model unavailable: {exc}')
    assert len(scores) == 2
    assert scores[0] > scores[1]
    assert all(-1 <= s <= 1.001 for s in scores)


def test_semantic_empty_candidates_never_load_model():
    from chronoverse.semantic import score_texts
    assert score_texts('query', []) == []
