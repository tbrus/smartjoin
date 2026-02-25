from smartjoin.joins.derived import detect_dominant_value_prefix


def test_detect_dominant_value_prefix_requires_support_and_sample_floor() -> None:
    values = [f"prod-{i:05d}" for i in range(1, 31)] + [f"cust-{i:05d}" for i in range(1, 11)]
    assert detect_dominant_value_prefix(values) == "prod"

    sparse_values = [f"prod-{i:05d}" for i in range(1, 10)]
    assert detect_dominant_value_prefix(sparse_values) is None
