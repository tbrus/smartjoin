from smartjoin.joins.derived import transform_description


def test_transform_description_known_transforms() -> None:
    assert transform_description("strip_non_alnum", {}) == "Strip non-alphanumeric characters"
    assert transform_description("remove_prefix", {"prefix": "prod-"}) == "Remove prefix 'prod-'"
    assert (
        transform_description("replace_prefix", {"from": "prod", "to": "prd"})
        == "Replace prefix 'prod' -> 'prd'"
    )


def test_transform_description_unknown_transform_is_deterministic() -> None:
    assert (
        transform_description("custom_transform", {"b": 2, "a": 1}) == "Custom transform (a=1, b=2)"
    )
