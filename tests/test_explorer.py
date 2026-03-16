import json
import math
from pathlib import Path

import polars as pl

from smartjoin.explorer import _jsonable, build_explorer


def test_build_explorer_writes_html_and_json(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "explorer"
    data_dir.mkdir(parents=True, exist_ok=True)

    pl.DataFrame({"customer_id": [1, 2, 3], "name": ["a", "b", "c"]}).write_csv(
        data_dir / "customers.csv"
    )
    pl.DataFrame({"order_id": [10, 11, 12], "customer_id": [1, 2, 2]}).write_csv(
        data_dir / "orders.csv"
    )

    index_path, data_path = build_explorer(
        path=data_dir,
        out_dir=out_dir,
        sample_rows=100,
        preview_rows=5,
        min_confidence=0.6,
    )

    assert index_path.exists()
    assert data_path.exists()

    html = index_path.read_text(encoding="utf-8")
    assert "smartjoinEmbeddedData" in html
    assert "__SMARTJOIN_EMBEDDED_DATA__" not in html
    assert "modeToggle" in html
    assert "relationshipTypeFilter" in html
    assert "derivedFilter" in html
    assert "metricAvgConfidence" in html
    assert "joinsFoundList" in html
    assert "missingJoinsList" in html
    assert "unexpectedJoinsList" in html
    assert "relationshipInspector" in html
    assert "Discovered Joins" in html
    assert "Missing Joins" in html
    assert "Unexpected Joins" in html
    assert "All discovered" in html
    assert "Discovered Join" in html
    assert "No manifest.json found. Showing discovered relationships only." in html
    assert "edge-unknown" in html
    assert "attachDrag" in html
    assert "derived?.description" in html
    assert "Core Relationships" not in html

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    assert "tables" in payload
    assert "report" in payload
    assert "joins" in payload["report"]
    assert "manifest" in payload


def test_build_explorer_includes_manifest_when_available(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "explorer"
    data_dir.mkdir(parents=True, exist_ok=True)

    pl.DataFrame({"customer_id": [1, 2], "name": ["a", "b"]}).write_csv(data_dir / "customers.csv")
    pl.DataFrame({"order_id": [10, 11], "customer_id": [1, 2]}).write_csv(data_dir / "orders.csv")
    (data_dir / "manifest.json").write_text(
        json.dumps(
            {
                "expected_joins": ["orders.customer_id -> customers.customer_id"],
                "trap_columns": ["country"],
                "ground_truth": {
                    "core_relationships": [
                        {
                            "from_table": "orders",
                            "from_column": "customer_id",
                            "to_table": "customers",
                            "to_column": "customer_id",
                        }
                    ],
                    "traps": {"overlapping_value_traps": []},
                },
            }
        ),
        encoding="utf-8",
    )

    _, data_path = build_explorer(
        path=data_dir,
        out_dir=out_dir,
        sample_rows=100,
        preview_rows=5,
        min_confidence=0.6,
    )

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    assert payload["manifest"] is not None
    assert payload["manifest"]["expected_joins"]


def test_jsonable_sanitizes_non_finite_floats() -> None:
    payload = {"nan_value": math.nan, "inf_value": math.inf, "nested": [1.0, -math.inf]}
    out = _jsonable(payload)
    assert out == {"nan_value": None, "inf_value": None, "nested": [1.0, None]}
