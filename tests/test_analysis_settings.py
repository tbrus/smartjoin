from pathlib import Path

import polars as pl

from smartjoin.analysis import analyze_path


def test_analysis_report_includes_settings_dump(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    pl.DataFrame({"customer_id": [1, 2, 3], "name": ["a", "b", "c"]}).write_csv(
        data_dir / "customers.csv"
    )
    pl.DataFrame({"order_id": [10, 11, 12], "customer_id": [1, 2, 2]}).write_csv(
        data_dir / "orders.csv"
    )

    report = analyze_path(
        path=data_dir,
        sample_rows=123,
        sample_seed=9,
        min_confidence=0.67,
        top_k_edges=2,
        distinct_low_card_threshold=11,
        near_unique_threshold=0.88,
        date_caps={"temporal_overlap": 0.61, "mixed_temporal": 0.73},
    )

    assert report.settings.min_confidence == 0.67
    assert report.settings.retention_confidence_floor == 0.0
    assert report.settings.top_k_edges == 2
    assert report.settings.sample_rows == 123
    assert report.settings.sample_seed == 9
    assert report.settings.distinct_low_card_threshold == 11
    assert report.settings.near_unique_threshold == 0.88
    assert report.settings.date_caps["temporal_overlap"] == 0.61
    assert report.settings.date_caps["mixed_temporal"] == 0.73
    assert report.settings.derived_conf_mult == 0.95
    assert report.graph.top_k_per_pair == 2
    assert report.graph.min_confidence == 0.67
