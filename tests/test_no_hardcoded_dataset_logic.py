from pathlib import Path


def test_core_inference_modules_do_not_embed_dataset_table_names() -> None:
    """
    Guard against accidentally hard-coding synthetic e-commerce dataset names
    in core inference logic.
    """
    root = Path(__file__).resolve().parents[1]
    core_files = [
        root / "src" / "alchemia" / "joins" / "discovery.py",
        root / "src" / "alchemia" / "keys" / "discovery.py",
        root / "src" / "alchemia" / "profiling" / "profiler.py",
        root / "src" / "alchemia" / "graphing.py",
    ]
    forbidden_tokens = [
        "customers",
        "products",
        "orders",
        "order_items",
        "payments",
        "shipments",
        "refunds",
        "promotions",
        "order_promotions",
        "region_code",
    ]

    for path in core_files:
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden_tokens:
            assert f'"{token}"' not in text
