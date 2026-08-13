from pathlib import Path

from .train_nfl_scores import load_rows, probability_above


def test_probability_above_is_smoothed_and_monotonic():
    residuals = __import__('numpy').asarray([-2, -1, 0, 1, 2] * 20, dtype=float)
    assert 0 < probability_above(50, 50, residuals) < 1
    assert probability_above(51, 50, residuals) > probability_above(49, 50, residuals)


def test_score_loader_rejects_post_event_knowledge(tmp_path: Path):
    path = tmp_path / 'score.jsonl'
    path.write_text('{"event_id":"x","event_time":"2025-01-01T12:00:00+00:00","knowledge_time":"2025-01-01T12:01:00+00:00","features":{},"total_points":44,"home_margin":3}\n')
    try:
        load_rows(path)
        assert False, 'expected leakage rejection'
    except ValueError as error:
        assert 'leaks future knowledge' in str(error)
