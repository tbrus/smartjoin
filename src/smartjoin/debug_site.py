"""Static debug site generator for relationship inspection."""

# ruff: noqa: E501

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from smartjoin.analysis import analyze_path
from smartjoin.ingestion import load_tables
from smartjoin.models import AnalysisReport


def _jsonable(value: Any) -> Any:
    """Convert a Python value to JSON-safe representation."""
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(inner) for key, inner in value.items()}
    return str(value)


def _load_manifest(path: Path) -> dict[str, Any] | None:
    """Load manifest metadata when available in analyzed directory."""
    if path.is_file():
        return None
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _example_match_key(value: Any) -> object | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    if not text:
        return None
    upper = text.upper()
    prefixed_numeric = re.fullmatch(r"0*([A-Z]+)[_\-\s]*0*([0-9]+)", upper)
    if prefixed_numeric:
        prefix, digits = prefixed_numeric.groups()
        return f"{prefix}{int(digits)}"
    numeric = re.fullmatch(r"0*([0-9]+)", upper)
    if numeric:
        return str(int(numeric.group(1)))
    return upper


def _example_display_value(value: Any) -> str:
    jsonable = _jsonable(value)
    if jsonable is None:
        return "null"
    return str(jsonable)


def _build_original_example_mappings(
    left_series: Any,
    right_series: Any,
    max_examples: int = 3,
    max_distinct_scan: int = 20_000,
) -> list[dict[str, str]]:
    left_values = (
        left_series.drop_nulls().unique(maintain_order=True).head(max_distinct_scan).to_list()
    )
    right_values = (
        right_series.drop_nulls().unique(maintain_order=True).head(max_distinct_scan).to_list()
    )
    right_lookup: dict[object, str] = {}
    for value in right_values:
        key = _example_match_key(value)
        if key is None or key in right_lookup:
            continue
        right_lookup[key] = _example_display_value(value)

    examples: list[dict[str, str]] = []
    seen_keys: set[object] = set()
    for value in left_values:
        key = _example_match_key(value)
        if key is None or key in seen_keys:
            continue
        right_value = right_lookup.get(key)
        if right_value is None:
            continue
        examples.append(
            {
                "from": _example_display_value(value),
                "to": right_value,
            }
        )
        seen_keys.add(key)
        if len(examples) >= max_examples:
            break
    return examples


def _build_payload(
    path: Path,
    sample_rows: int,
    sample_seed: int,
    preview_rows: int,
    max_tables: int | None,
    max_columns: int | None,
    min_confidence: float,
    graph_top_k_per_pair: int,
    distinct_low_card_threshold: int,
    near_unique_threshold: float,
    date_caps: dict[str, float] | None,
    fast_profile: bool,
    profile_entropy_cap: int,
    join_weights: dict[str, float] | None,
    xlsx_sheet_map: dict[str, str] | None,
    json_flatten_depth: int,
    llm_enabled: bool,
    llm_plugin: str | None,
    precomputed_report: AnalysisReport | None = None,
) -> dict[str, Any]:
    tables = load_tables(
        path=path,
        max_tables=max_tables,
        max_columns=max_columns,
        xlsx_sheet_map=xlsx_sheet_map,
        json_flatten_depth=json_flatten_depth,
    )
    report = precomputed_report or analyze_path(
        path=path,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        max_tables=max_tables,
        max_columns=max_columns,
        min_confidence=min_confidence,
        graph_top_k_per_pair=graph_top_k_per_pair,
        distinct_low_card_threshold=distinct_low_card_threshold,
        near_unique_threshold=near_unique_threshold,
        date_caps=date_caps,
        fast_profile=fast_profile,
        profile_entropy_cap=profile_entropy_cap,
        join_weights=join_weights,
        xlsx_sheet_map=xlsx_sheet_map,
        json_flatten_depth=json_flatten_depth,
        llm_enabled=llm_enabled,
        llm_plugin=llm_plugin,
    )

    profile_by_table = {table_profile.table_name: table_profile for table_profile in report.tables}
    key_by_table = {item.table_name: item for item in report.keys}

    table_payload: list[dict[str, Any]] = []
    for table in sorted(tables, key=lambda item: item.name.lower()):
        preview = table.df.head(preview_rows).to_dicts()
        preview = [{key: _jsonable(value) for key, value in row.items()} for row in preview]
        table_profile = profile_by_table[table.name]
        key_profile = key_by_table[table.name]
        column_stats = {
            column.name: column.model_dump(mode="json") for column in table_profile.columns
        }
        columns = []
        for col_name, col_dtype in table.df.schema.items():
            columns.append(
                {
                    "name": col_name,
                    "dtype": str(col_dtype),
                    "profile": column_stats.get(col_name, {}),
                }
            )
        table_payload.append(
            {
                "name": table.name,
                "row_count": table.df.height,
                "columns": columns,
                "sample_rows": preview,
                "primary_key_candidates": [
                    candidate.model_dump(mode="json")
                    for candidate in key_profile.primary_key_candidates[:3]
                ],
                "composite_key_candidates": [
                    candidate.model_dump(mode="json")
                    for candidate in key_profile.composite_key_candidates[:3]
                ],
            }
        )

    manifest = _load_manifest(path)
    report_payload = report.model_dump(mode="json")
    table_by_name = {table.name: table for table in tables}
    for join in report_payload.get("joins", []):
        if not isinstance(join, dict):
            continue
        if join.get("derived") is not None:
            continue
        left_table = join.get("left_table")
        left_column = join.get("left_column")
        right_table = join.get("right_table")
        right_column = join.get("right_column")
        if not all(
            isinstance(item, str)
            for item in [left_table, left_column, right_table, right_column]
        ):
            continue
        left = table_by_name.get(left_table)
        right = table_by_name.get(right_table)
        if left is None or right is None:
            continue
        if left_column not in left.df.columns or right_column not in right.df.columns:
            continue
        join["example_mappings"] = _build_original_example_mappings(
            left_series=left.df.get_column(left_column),
            right_series=right.df.get_column(right_column),
            max_examples=3,
        )

    return {
        "meta": {
            "source_path": str(path.resolve()),
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "preview_rows": preview_rows,
            "sample_rows": sample_rows,
            "sample_seed": sample_seed,
            "min_confidence": min_confidence,
            "graph_top_k_per_pair": graph_top_k_per_pair,
            "distinct_low_card_threshold": distinct_low_card_threshold,
            "near_unique_threshold": near_unique_threshold,
            "date_caps": date_caps or {},
            "fast_profile": fast_profile,
            "profile_entropy_cap": profile_entropy_cap,
        },
        "manifest": manifest,
        "report": report_payload,
        "tables": table_payload,
    }


DEBUG_SITE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Smartjoin Debug Viewer</title>
  <style>
    :root{
      --bg:#edf3f9;
      --bg-2:#f8f1e8;
      --surface:rgba(255,255,255,0.8);
      --surface-strong:#ffffff;
      --surface-soft:#f7fafc;
      --ink:#10212d;
      --muted:#5d7081;
      --edge:#da8a42;
      --edge-found:#1f9a63;
      --edge-missing:#d44958;
      --edge-unexpected:#1c5cb8;
      --accent:#0f7ea8;
      --accent-soft:#d7eef8;
      --card:#ffffff;
      --border:rgba(16,33,45,0.14);
      --ring:rgba(15,126,168,0.25);
      --shadow-soft:0 10px 24px rgba(18, 35, 50, 0.08);
      --shadow-strong:0 22px 38px rgba(18, 35, 50, 0.14);
    }
    *{box-sizing:border-box}
    *::-webkit-scrollbar{width:10px;height:10px}
    *::-webkit-scrollbar-thumb{
      background:linear-gradient(180deg, rgba(113,133,150,0.58), rgba(84,103,120,0.6));
      border-radius:999px;
      border:2px solid transparent;
      background-clip:padding-box;
    }
    *::-webkit-scrollbar-track{background:transparent}
    body{
      margin:0;
      font-family:"Sora","IBM Plex Sans","Segoe UI",sans-serif;
      color:var(--ink);
      background:
        radial-gradient(1200px 460px at -12% -8%, #d2e8ff 0%, transparent 62%),
        radial-gradient(820px 360px at 108% -6%, #ffe7c4 0%, transparent 62%),
        linear-gradient(145deg, var(--bg) 0%, var(--bg-2) 100%);
      min-height:100vh;
      line-height:1.35;
      font-feature-settings:"cv10" 1,"ss01" 1;
    }
    .shell{
      display:grid;
      grid-template-columns:320px 1fr;
      min-height:100vh;
    }
    .sidebar{
      border-right:1px solid var(--border);
      background:rgba(255,255,255,0.66);
      backdrop-filter:blur(14px);
      padding:18px 16px 14px;
      overflow:auto;
      box-shadow:inset -1px 0 0 rgba(255,255,255,0.46);
    }
    .brand{
      margin:0 0 4px 0;
      font-size:1.24rem;
      letter-spacing:0.01em;
      font-weight:750;
      color:#0f2836;
    }
    .sub{
      margin:0 0 14px 0;
      color:var(--muted);
      font-size:0.84rem;
      line-height:1.46;
    }
    .panel{
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:14px;
      padding:12px;
      margin-bottom:12px;
      box-shadow:var(--shadow-soft);
      backdrop-filter:blur(8px);
    }
    .panel h3{
      margin:0 0 9px 0;
      font-size:0.72rem;
      text-transform:uppercase;
      letter-spacing:0.12em;
      color:var(--muted);
    }
    .control-stack{
      display:grid;
      gap:9px;
    }
    .tool-row{
      display:flex;
      gap:8px;
      flex-wrap:wrap;
    }
    .mini-btn{
      border:1px solid var(--border);
      background:linear-gradient(180deg, #fff 0%, #f1f7fb 100%);
      color:var(--ink);
      border-radius:999px;
      padding:7px 11px;
      cursor:pointer;
      font-size:0.77rem;
      font-weight:650;
      box-shadow:0 4px 10px rgba(17,45,65,0.07);
      transition:border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
    }
    .mini-btn:hover{
      border-color:rgba(16,33,45,0.3);
      transform:translateY(-1px);
      box-shadow:0 8px 18px rgba(17,45,65,0.12);
    }
    input[type="text"], select{
      width:100%;
      border:1px solid var(--border);
      border-radius:11px;
      padding:8px 10px;
      font-size:0.82rem;
      background:#fbfdff;
      color:var(--ink);
      transition:border-color 120ms ease, box-shadow 120ms ease, background 120ms ease;
    }
    input[type="text"]::placeholder{color:#8ea0ad}
    input[type="text"]:focus, select:focus{
      outline:none;
      border-color:rgba(15,126,168,0.55);
      box-shadow:0 0 0 3px var(--ring);
      background:#ffffff;
    }
    .tabs{
      display:flex;
      gap:8px;
      margin-bottom:12px;
      flex-wrap:wrap;
    }
    .tab{
      border:1px solid var(--border);
      background:linear-gradient(180deg, #fff 0%, #f1f6fb 100%);
      color:#214052;
      border-radius:999px;
      padding:7px 13px;
      cursor:pointer;
      font-size:0.82rem;
      font-weight:630;
      transition:all 140ms ease;
      box-shadow:0 4px 10px rgba(17,45,65,0.07);
    }
    .tab:hover{transform:translateY(-1px)}
    .tab.active{
      background:linear-gradient(145deg, #1186b5 0%, #0e6e93 100%);
      color:white;
      border-color:#0e6e93;
      box-shadow:0 8px 18px rgba(16,108,146,0.28);
    }
    .control-label{
      display:block;
      font-size:0.73rem;
      color:var(--muted);
      margin-bottom:6px;
      text-transform:uppercase;
      letter-spacing:0.08em;
    }
    input[type="range"], select{
      width:100%;
    }
    .table-list{
      list-style:none;
      padding:0;
      margin:0;
      display:grid;
      gap:8px;
    }
    .table-list button{
      width:100%;
      text-align:left;
      border:1px solid var(--border);
      background:linear-gradient(180deg, #fff 0%, #f7fbff 100%);
      border-radius:11px;
      padding:8px 10px;
      color:var(--ink);
      cursor:pointer;
      font-size:0.81rem;
      transition:all 140ms ease;
    }
    .table-list button:hover{
      border-color:rgba(16,33,45,0.28);
      transform:translateX(1px);
      box-shadow:0 8px 16px rgba(18,35,50,0.09);
    }
    .main{
      padding:18px;
      overflow:hidden;
      display:flex;
      flex-direction:column;
      gap:14px;
    }
    .coverage-strip{
      margin-bottom:0;
      padding:10px;
      background:linear-gradient(120deg, rgba(255,255,255,0.88), rgba(242,249,255,0.9));
    }
    .metric-grid{
      display:grid;
      gap:9px;
      grid-template-columns:repeat(8, minmax(88px, 1fr));
    }
    .metric-card{
      border:1px solid var(--border);
      border-radius:12px;
      background:linear-gradient(160deg, #ffffff 0%, #f4f8fc 100%);
      padding:9px 9px 10px;
      box-shadow:0 5px 14px rgba(18,35,50,0.08);
      position:relative;
      overflow:hidden;
    }
    .metric-card::after{
      content:"";
      position:absolute;
      top:0;
      left:0;
      right:0;
      height:2px;
      background:linear-gradient(90deg, #1b93c7 0%, #23a46e 100%);
      opacity:0.7;
    }
    .metric-label{
      display:block;
      color:var(--muted);
      font-size:0.65rem;
      text-transform:uppercase;
      letter-spacing:0.1em;
      margin-bottom:4px;
    }
    .metric-value{
      display:block;
      font-size:1rem;
      font-weight:760;
      line-height:1.1;
      color:#0f2836;
    }
    .workspace-shell{
      display:grid;
      grid-template-columns:minmax(0,1fr) 380px;
      gap:14px;
      align-items:flex-start;
      margin-bottom:14px;
    }
    .graph-panel{
      resize:vertical;
      overflow:auto;
      min-height:360px;
      max-height:72vh;
      border-radius:16px;
      border:1px solid var(--border);
      background:rgba(255,255,255,0.95);
      box-shadow:var(--shadow-strong);
      height:100%;
    }
    .graph-layout{
      min-height:0;
    }
    .graph-panel .canvas-wrap{
      border:none;
      background:transparent;
      min-height:320px;
      border-radius:14px;
    }
    .canvas-wrap{
      position:relative;
      border:1px solid var(--border);
      background:rgba(255,255,255,0.86);
      border-radius:16px;
      box-shadow:var(--shadow-strong);
      min-height:680px;
      overflow:auto;
    }
    .diagram-canvas{
      position:relative;
      width:1800px;
      height:1200px;
      background:
        linear-gradient(transparent 31px, rgba(120,140,160,0.08) 32px),
        linear-gradient(90deg, transparent 31px, rgba(120,140,160,0.08) 32px);
      background-size:32px 32px;
    }
    .edge-layer{
      position:absolute;
      inset:0;
      width:100%;
      height:100%;
      overflow:visible;
      pointer-events:auto;
      z-index:2;
    }
    .edge-layer path{
      fill:none;
      stroke:var(--edge);
      stroke-width:1.9;
      opacity:0.72;
      pointer-events:stroke;
      cursor:pointer;
      transition:opacity 140ms ease, stroke-width 140ms ease, stroke 140ms ease, filter 140ms ease;
    }
    .edge-layer path.edge-found{stroke:var(--edge-found)}
    .edge-layer path.edge-missing{stroke:var(--edge-missing)}
    .edge-layer path.edge-unexpected{stroke:var(--edge-unexpected)}
    .edge-layer path.edge-unknown{stroke:var(--edge)}
    .edge-layer path.derived-edge{stroke-dasharray:6 6}
    .edge-layer path.selected{
      stroke-width:3.5;
      opacity:1;
      filter:drop-shadow(0 0 4px rgba(20,32,45,0.34));
    }
    .edge-layer path:hover{
      opacity:1;
      stroke-width:2.8;
    }
    .table-card{
      position:absolute;
      width:282px;
      background:var(--card);
      border:1px solid var(--border);
      border-radius:14px;
      box-shadow:0 16px 30px rgba(20,37,52,0.16);
      overflow:hidden;
      z-index:3;
      transition:transform 160ms ease, opacity 160ms ease, box-shadow 160ms ease;
      animation:tableIn 260ms ease both;
      transform-origin:center top;
    }
    .table-card:hover{
      transform:translateY(-2px);
      box-shadow:0 20px 36px rgba(20,37,52,0.2);
    }
    .table-card.dimmed{
      opacity:0.24;
      filter:saturate(0.8);
    }
    .table-head{
      background:linear-gradient(120deg,#f2f9ff 0%,#eaf6f2 100%);
      border-bottom:1px solid var(--border);
      padding:10px 12px;
      cursor:grab;
      user-select:none;
      touch-action:none;
    }
    .table-head.dragging{cursor:grabbing}
    .table-head h4{
      margin:0;
      font-size:0.89rem;
      letter-spacing:0.01em;
    }
    .table-head span{
      color:var(--muted);
      font-size:0.74rem;
    }
    .column-list{
      list-style:none;
      margin:0;
      padding:0;
      max-height:320px;
      overflow:auto;
    }
    .column-list li{
      display:flex;
      justify-content:space-between;
      gap:8px;
      padding:7px 10px;
      border-bottom:1px dashed rgba(16,33,45,0.14);
      font-family:"IBM Plex Mono","Fira Code","Consolas",monospace;
      font-size:0.73rem;
      background:#ffffff;
    }
    .column-list li:nth-child(even){background:#fbfdff}
    .column-list li.join-col{
      background:var(--accent-soft);
      color:#0f5f7d;
      font-weight:600;
    }
    .data-grid,.truth-grid{
      border:1px solid var(--border);
      border-radius:16px;
      background:rgba(255,255,255,0.9);
      box-shadow:var(--shadow-strong);
      display:flex;
      flex-direction:column;
      min-height:260px;
      overflow:hidden;
    }
    .data-toolbar{
      display:flex;
      gap:10px;
      padding:12px;
      border-bottom:1px solid var(--border);
      align-items:center;
      flex-wrap:wrap;
      background:linear-gradient(120deg, #f7fbff 0%, #edf6fa 100%);
    }
    .table-preview{
      overflow:auto;
      padding:12px;
      height:100%;
    }
    .truth-content{
      overflow:auto;
      padding:12px;
      height:100%;
      display:grid;
      gap:12px;
      grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
      align-content:start;
    }
    .right-rail{
      border:1px solid var(--border);
      border-radius:16px;
      background:rgba(255,255,255,0.9);
      box-shadow:var(--shadow-strong);
      overflow:auto;
      padding:12px;
      align-self:stretch;
      min-height:360px;
    }
    .right-rail h3{
      margin:0 0 10px 0;
      font-size:0.73rem;
      text-transform:uppercase;
      letter-spacing:0.12em;
      color:var(--muted);
    }
    .rail-section{
      border:1px solid var(--border);
      border-radius:12px;
      background:linear-gradient(160deg, #ffffff 0%, #f7fbff 100%);
      padding:10px;
      margin-bottom:10px;
      box-shadow:0 6px 14px rgba(18,35,50,0.08);
    }
    .rail-section h4{
      margin:0 0 8px 0;
      font-size:0.74rem;
      letter-spacing:0.1em;
      text-transform:uppercase;
      color:var(--muted);
    }
    .rail-list{
      font-size:0.79rem;
      line-height:1.42;
      padding-right:4px;
    }
    .rail-list ul{
      margin:0;
      padding-left:16px;
      display:grid;
      gap:4px;
    }
    .rail-section.found h4{ color:var(--edge-found); }
    .rail-section.missing h4{ color:var(--edge-missing); }
    .rail-section.unexpected h4{ color:var(--edge-unexpected); }
    .rail-section.found .rail-list li{ color:var(--edge-found); }
    .rail-section.missing .rail-list li{ color:var(--edge-missing); }
    .rail-section.unexpected .rail-list li{ color:var(--edge-unexpected); }
    .truth-card{
      border:1px solid var(--border);
      border-radius:12px;
      background:#fffdf8;
      padding:10px;
    }
    .truth-card h4{
      margin:0 0 8px 0;
      font-size:0.82rem;
      letter-spacing:0.06em;
      text-transform:uppercase;
      color:var(--muted);
    }
    .truth-card ul{
      margin:0;
      padding-left:16px;
      font-size:0.8rem;
      line-height:1.4;
      display:grid;
      gap:4px;
    }
    .truth-stat{
      font-size:0.82rem;
      color:var(--ink);
      line-height:1.45;
    }
    table.preview{
      border-collapse:separate;
      border-spacing:0;
      width:100%;
      min-width:760px;
      background:white;
      border:1px solid rgba(16,33,45,0.14);
      border-radius:12px;
      overflow:hidden;
    }
    table.preview th,table.preview td{
      border-bottom:1px solid rgba(16,33,45,0.1);
      padding:7px 8px;
      font-size:0.78rem;
      text-align:left;
      white-space:nowrap;
    }
    table.preview td+td, table.preview th+th{border-left:1px solid rgba(16,33,45,0.08)}
    table.preview th{
      position:sticky;
      top:0;
      background:linear-gradient(120deg, #eef6fd 0%, #e8f4ef 100%);
      z-index:2;
      font-weight:700;
      font-size:0.74rem;
      text-transform:uppercase;
      letter-spacing:0.05em;
      color:#26485c;
    }
    .hint{
      font-size:0.77rem;
      color:var(--muted);
      line-height:1.45;
    }
    .truth-badge{
      display:inline-block;
      border-radius:999px;
      padding:3px 9px;
      font-size:0.7rem;
      font-weight:750;
      letter-spacing:0.04em;
      margin-bottom:7px;
      text-transform:uppercase;
    }
    .truth-badge.found{
      background:#dff8ea;
      color:#1b7d4e;
      border:1px solid #8fd3ad;
    }
    .truth-badge.unexpected{
      background:#e4ecff;
      color:#1a3b74;
      border:1px solid #9ab6f6;
    }
    .truth-badge.missing{
      background:#ffe6e9;
      color:#a52f3f;
      border:1px solid #efabb5;
    }
    .truth-badge.unknown{
      background:#fff0e4;
      color:#b56026;
      border:1px solid #f0c8a8;
    }
    .edge-tooltip{
      position:fixed;
      pointer-events:none;
      background:rgba(15,30,50,0.96);
      color:#f2f6ff;
      border-radius:12px;
      padding:10px 14px;
      box-shadow:0 12px 30px rgba(15,30,50,0.35);
      font-size:0.82rem;
      line-height:1.35;
      z-index:20;
      max-width:300px;
      display:none;
    }
    @keyframes tableIn{
      from{ opacity:0; transform:translateY(8px) scale(0.985); }
      to{ opacity:1; transform:translateY(0) scale(1); }
    }
    @media (max-width:1500px){
      .metric-grid{
        grid-template-columns:repeat(4, minmax(90px, 1fr));
      }
      .workspace-shell{
        grid-template-columns:1fr;
      }
      .right-rail{
        min-height:420px;
      }
    }
    @media (max-width:1200px){
      .shell{grid-template-columns:1fr}
      .sidebar{
        border-right:0;
        border-bottom:1px solid var(--border);
        box-shadow:none;
      }
      .main{padding:12px}
      .diagram-canvas{width:1300px;height:1000px}
      .metric-grid{
        grid-template-columns:repeat(2, minmax(120px, 1fr));
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <h1 class="brand">Smartjoin Debug Viewer</h1>
      <p class="sub">Relationship map and table previews for debugging inference output.</p>
      <section class="panel">
        <h3>Filter</h3>
        <div class="control-stack">
          <label class="control-label" for="confidenceRange">Min confidence</label>
          <input id="confidenceRange" type="range" min="0" max="1" step="0.01" value="0.75">
          <div class="hint">Current threshold: <strong id="confidenceLabel">0.75</strong></div>

          <label class="control-label" for="tableSearch">Table/column search</label>
          <input id="tableSearch" type="text" placeholder="Try: orders, customer_id, payment">

          <label class="control-label" for="edgeMode">Edge type</label>
          <select id="edgeMode">
            <option value="all">All relationships</option>
            <option value="found">Joins Found</option>
            <option value="missing">Missing Joins</option>
            <option value="unexpected">Unexpected Joins</option>
          </select>

          <div class="tool-row">
            <button class="mini-btn" id="relayoutBtn">Auto Layout</button>
            <button class="mini-btn" id="fitViewBtn">Fit Visible</button>
            <button class="mini-btn" id="clearFilterBtn">Clear Filters</button>
          </div>

          <div class="hint">
            Visible joins: <strong id="visibleJoinCount">0</strong>
          </div>
        </div>
      </section>
      <section class="panel">
        <h3>Tables</h3>
        <ul id="tableList" class="table-list"></ul>
      </section>
    </aside>
    <main class="main">
      <section class="panel coverage-strip">
        <div class="metric-grid">
          <div class="metric-card"><span class="metric-label">Expected</span><span class="metric-value" id="covExpected">0</span></div>
          <div class="metric-card"><span class="metric-label">Predicted</span><span class="metric-value" id="covPredicted">0</span></div>
          <div class="metric-card"><span class="metric-label">Found</span><span class="metric-value" id="covFound">0</span></div>
          <div class="metric-card"><span class="metric-label">Missing</span><span class="metric-value" id="covMissing">0</span></div>
          <div class="metric-card"><span class="metric-label">Unexpected</span><span class="metric-value" id="covUnexpected">0</span></div>
          <div class="metric-card"><span class="metric-label">Recall</span><span class="metric-value" id="covRecall">0.0%</span></div>
          <div class="metric-card"><span class="metric-label">Precision</span><span class="metric-value" id="covPrecision">0.0%</span></div>
          <div class="metric-card"><span class="metric-label">Threshold</span><span class="metric-value" id="covThreshold">0.75</span></div>
        </div>
      </section>
      <div class="workspace-shell">
        <div class="graph-layout">
          <div class="graph-panel">
            <section id="diagramView" class="canvas-wrap active">
              <div id="diagramCanvas" class="diagram-canvas">
                <svg id="edgeLayer" class="edge-layer"></svg>
              </div>
            </section>
          </div>
        </div>
        <aside class="right-rail">
          <h3>Evaluation</h3>
          <section class="rail-section found">
            <h4>Joins Found</h4>
            <div class="rail-list" id="joinsFoundList"></div>
          </section>
          <section class="rail-section missing">
            <h4>Missing Joins</h4>
            <div class="rail-list" id="missingJoinsList"></div>
          </section>
          <section class="rail-section unexpected">
            <h4>Unexpected Joins</h4>
            <div class="rail-list" id="unexpectedJoinsList"></div>
          </section>
        </aside>
      </div>
      <section id="dataView" class="data-grid">
        <div class="data-toolbar">
          <label class="control-label" for="tableSelect">Table</label>
          <select id="tableSelect"></select>
          <span class="hint" id="tableMeta"></span>
        </div>
        <div id="tablePreview" class="table-preview"></div>
      </section>
    </main>
  </div>
  <div id="edgeTooltip" class="edge-tooltip">Hover an edge to inspect the relationship.</div>
  <script id="smartjoinEmbeddedData" type="application/json">__SMARTJOIN_EMBEDDED_DATA__</script>
  <script>
    const state = {
      payload: null,
      threshold: 0.75,
      tablePositions: {},
      currentRelationships: [],
      matchingTables: new Set(),
      tableQuery: "",
      edgeMode: "all",
      selectedRelationshipKey: null,
      relationshipPool: [],
    };
    const tooltipEl = document.getElementById("edgeTooltip");

    const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

    function tableByName(name) {
      return state.payload.tables.find((t) => t.name === name);
    }

    function activeRelationships() {
      const matchingTables = refreshMatchingTables();
      return state.relationshipPool.filter((rel) => {
        if (rel.category !== "missing" && rel.confidence < state.threshold) return false;
        if (matchingTables.size > 0) {
          if (!(matchingTables.has(rel.left_table) || matchingTables.has(rel.right_table))) {
            return false;
          }
        }
        if (state.edgeMode !== "all" && rel.category !== state.edgeMode) {
          return false;
        }
        return true;
      });
    }

    function splitRef(ref) {
      if (!ref || typeof ref !== "string") return { table: "", column: "" };
      const dotIndex = ref.indexOf(".");
      if (dotIndex < 0) return { table: ref.trim(), column: "" };
      return {
        table: ref.slice(0, dotIndex).trim(),
        column: ref.slice(dotIndex + 1).trim(),
      };
    }

    function annotateJoin(join, expectedKeys, hasGroundTruth) {
      const left = `${join.left_table}.${join.left_column}`;
      const right = `${join.right_table}.${join.right_column}`;
      const key = relationKey(left, right);
      let category = expectedKeys.has(key) ? "found" : "unexpected";
      if (!hasGroundTruth) category = "found";
      return {
        ...join,
        key,
        display: joinDisplay(left, right),
        category,
      };
    }

    function buildMissingRelationship(info, key) {
      return {
        left_table: info.left_table,
        left_column: info.left_column,
        right_table: info.right_table,
        right_column: info.right_column,
        confidence: 1,
        relationship_guess: info.relationship_guess || "ground_truth",
        breakdown: { signals: {}, weights: {}, weighted_score: 0 },
        category: "missing",
        display: info.display,
        key,
      };
    }

    function buildRelationshipPool(expectedMap, predictedJoins, hasGroundTruth) {
      const expectedKeys = expectedMap ? new Set(expectedMap.keys()) : new Set();
      const predictedKeys = new Set();
      const pool = predictedJoins.map((join) => {
        const annotated = annotateJoin(join, expectedKeys, hasGroundTruth);
        predictedKeys.add(annotated.key);
        return annotated;
      });
      if (expectedMap && expectedMap.size > 0) {
        expectedMap.forEach((info, key) => {
          if (!predictedKeys.has(key)) {
            pool.push(buildMissingRelationship(info, key));
          }
        });
      }
      return pool;
    }

    function formatTooltipContent(rel, truthState) {
      const left = `${rel.left_table}.${rel.left_column}`;
      const right = `${rel.right_table}.${rel.right_column}`;
      const labelMap = {
        found: "Join Found",
        missing: "Missing Join",
        unexpected: "Unexpected Join",
        unknown: "Unlabeled Join",
      };
      const label = labelMap[truthState] || labelMap.unknown;
      const derived = rel.derived || null;
      const derivedDescription = String(derived?.description || "").trim();
      const derivedExamples = (derived?.example_mappings || [])
        .slice(0, 3)
        .map((item) => {
          const from = String(item?.from ?? "");
          const to = String(item?.to ?? "");
          if (!from && !to) return "";
          return `<div>${from} -> ${to}</div>`;
        })
        .filter(Boolean)
        .join("");
      const originalExamples = (rel.example_mappings || [])
        .slice(0, 3)
        .map((item) => {
          const from = String(item?.from ?? "");
          const to = String(item?.to ?? "");
          if (!from && !to) return "";
          return `<div>${from} -> ${to}</div>`;
        })
        .filter(Boolean)
        .join("");
      const derivedSection = derived
        ? `
          <div style="margin-top:6px; padding:6px 8px; border:1px dashed var(--border); border-radius:8px; background:rgba(255,255,255,0.68);">
            <div style="font-weight:600; font-size:0.76rem; margin-bottom:3px;">Derived column</div>
            <div style="font-size:0.75rem;">${
              derivedDescription ||
              `Transform ${String(derived.transform_id || "")} ${JSON.stringify(derived.params || {})}`
            }</div>
            ${derivedExamples ? `<div style="margin-top:4px; font-size:0.74rem;">${derivedExamples}</div>` : ""}
          </div>
        `
        : "";
      const originalSection = !derived
        ? `
          <div style="margin-top:6px; padding:6px 8px; border:1px dashed var(--border); border-radius:8px; background:rgba(255,255,255,0.68);">
            <div style="font-weight:600; font-size:0.76rem; margin-bottom:3px;">Original column</div>
            ${
              originalExamples
                ? `<div style="margin-top:4px; font-size:0.74rem;">${originalExamples}</div>`
                : `<div style="margin-top:4px; font-size:0.74rem;">no sample mappings</div>`
            }
          </div>
        `
        : "";
      const signals = Object.entries(rel.breakdown?.signals || {})
        .map(([k, v]) => `<div><strong>${k}</strong>: ${Number(v).toFixed(3)}</div>`)
        .join("");
      return `
        <div style="font-weight:600; margin-bottom:4px;">${label}</div>
        <div>${left} -> ${right}</div>
        <div style="margin-top:6px; font-size:0.78rem;">confidence: ${rel.confidence.toFixed(3)}</div>
        <div style="font-size:0.78rem;">relationship: ${rel.relationship_guess}</div>
        ${derivedSection}
        ${originalSection}
        ${signals ? `<div style="margin-top:6px; font-size:0.75rem;">${signals}</div>` : ""}
      `;
    }

    function positionTooltip(event) {
      if (!tooltipEl) return;
      const offset = 12;
      const x = event.clientX + offset;
      const y = event.clientY + offset;
      tooltipEl.style.left = `${x}px`;
      tooltipEl.style.top = `${y}px`;
    }

    function showTooltip(rel, truthState, event) {
      if (!tooltipEl) return;
      tooltipEl.innerHTML = formatTooltipContent(rel, truthState);
      positionTooltip(event);
      tooltipEl.style.display = "block";
    }

    function joinDisplay(left, right) {
      return `${left} -> ${right}`;
    }

    function sortStrings(items) {
      return [...(items || [])].sort((a, b) => String(a).localeCompare(String(b)));
    }

    function dedupeStrings(items) {
      const out = [];
      const seen = new Set();
      (items || []).forEach((item) => {
        const text = String(item ?? "").trim();
        if (!text || seen.has(text)) return;
        seen.add(text);
        out.push(text);
      });
      return out;
    }

    function tableMatchesQuery(table) {
      const query = state.tableQuery.trim().toLowerCase();
      if (!query) return true;
      if (table.name.toLowerCase().includes(query)) return true;
      return table.columns.some((col) => String(col.name || "").toLowerCase().includes(query));
    }

    function refreshMatchingTables() {
      const set = new Set();
      state.payload.tables.forEach((table) => {
        if (tableMatchesQuery(table)) set.add(table.name);
      });
      state.matchingTables = set;
      return set;
    }

    function relationshipColumnsByTable() {
      const map = new Map();
      activeRelationships().forEach((rel) => {
        if (!map.has(rel.left_table)) map.set(rel.left_table, new Set());
        if (!map.has(rel.right_table)) map.set(rel.right_table, new Set());
        map.get(rel.left_table).add(rel.left_column);
        map.get(rel.right_table).add(rel.right_column);
      });
      return map;
    }

    function renderTableList() {
      const list = document.getElementById("tableList");
      list.innerHTML = "";
      const matching = refreshMatchingTables();
      const visibleTables = state.payload.tables.filter((table) => matching.has(table.name));
      visibleTables.forEach((table) => {
        const button = document.createElement("button");
        button.textContent = `${table.name} (${table.row_count.toLocaleString()} rows)`;
        button.addEventListener("click", () => {
          document.getElementById("tableSelect").value = table.name;
          renderTablePreview();
          switchToData();
        });
        const li = document.createElement("li");
        li.appendChild(button);
        list.appendChild(li);
      });
      if (visibleTables.length === 0) {
        list.innerHTML = `<li><div class="hint">No tables match current filter.</div></li>`;
      }
    }

    function buildCard(table, joinCols) {
      const card = document.createElement("article");
      card.className = "table-card";
      card.dataset.table = table.name;

      const head = document.createElement("div");
      head.className = "table-head";
      head.innerHTML = `<h4>${table.name}</h4><span>${table.row_count.toLocaleString()} rows</span>`;
      card.appendChild(head);

      const ul = document.createElement("ul");
      ul.className = "column-list";
      table.columns.forEach((column) => {
        const li = document.createElement("li");
        li.dataset.column = column.name;
        if (joinCols?.has(column.name)) li.classList.add("join-col");
        const left = document.createElement("span");
        left.textContent = column.name;
        const right = document.createElement("span");
        right.textContent = column.dtype;
        li.append(left, right);
        ul.appendChild(li);
      });
      card.appendChild(ul);
      return card;
    }

    function layoutPosition(index, total) {
      const cols = Math.max(2, Math.ceil(Math.sqrt(total)));
      const row = Math.floor(index / cols);
      const col = index % cols;
      return { x: 80 + col * 340, y: 60 + row * 300 };
    }

    function drawEdges(relationships, canvas, edgeLayer) {
      edgeLayer.innerHTML = "";
      const width = canvas.clientWidth || 1800;
      const height = canvas.clientHeight || 1200;
      edgeLayer.setAttribute("width", String(width));
      edgeLayer.setAttribute("height", String(height));
      edgeLayer.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const rect = canvas.getBoundingClientRect();

      relationships.forEach((rel) => {
        const leftEl = findColumnElement(canvas, rel.left_table, rel.left_column);
        const rightEl = findColumnElement(canvas, rel.right_table, rel.right_column);
        const leftCard = findTableCard(canvas, rel.left_table);
        const rightCard = findTableCard(canvas, rel.right_table);
        if (!leftCard || !rightCard) return;

        const leftAnchor =
          leftEl ||
          leftCard.querySelector(".table-head") ||
          leftCard;
        const rightAnchor =
          rightEl ||
          rightCard.querySelector(".table-head") ||
          rightCard;

        const a = leftAnchor.getBoundingClientRect();
        const b = rightAnchor.getBoundingClientRect();
        const x1 = (leftEl ? a.right : a.left + a.width * 0.95) - rect.left;
        const y1 = a.top + a.height / 2 - rect.top;
        const x2 = (rightEl ? b.left : b.left + b.width * 0.05) - rect.left;
        const y2 = b.top + b.height / 2 - rect.top;
        const bend = clamp((x2 - x1) * 0.5, 60, 220);
        const leftRef = `${rel.left_table}.${rel.left_column}`;
        const rightRef = `${rel.right_table}.${rel.right_column}`;
        const relKey = relationKey(leftRef, rightRef);
        const category = rel.category || "unknown";
        const truthState =
          category === "missing"
            ? "missing"
            : category === "unexpected"
            ? "unexpected"
            : category === "found"
            ? "found"
            : "unknown";

        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
        path.setAttribute("stroke-opacity", String(clamp(rel.confidence, 0.25, 1)));
        path.classList.add(`edge-${truthState}`);
        if (rel.derived) {
          path.classList.add("derived-edge");
        }
        if (state.selectedRelationshipKey === relKey) {
          path.classList.add("selected");
        }
        path.dataset.edge = JSON.stringify(rel);
        path.style.pointerEvents = "stroke";
        path.addEventListener("click", () => {
          state.selectedRelationshipKey = relKey;
          drawEdges(state.currentRelationships, canvas, edgeLayer);
        });
        if (tooltipEl) {
          path.addEventListener("pointerenter", (event) => {
            showTooltip(rel, truthState, event);
          });
          path.addEventListener("pointermove", (event) => {
            positionTooltip(event);
          });
          path.addEventListener("pointerleave", () => {
            tooltipEl.style.display = "none";
          });
        }
        edgeLayer.appendChild(path);
      });
    }

    function findColumnElement(canvas, tableName, columnName) {
      const cards = canvas.querySelectorAll(".table-card");
      for (const card of cards) {
        if (card.dataset.table !== tableName) continue;
        const cols = card.querySelectorAll("li[data-column]");
        for (const col of cols) {
          if (col.dataset.column === columnName) return col;
        }
      }
      return null;
    }

    function findTableCard(canvas, tableName) {
      const cards = canvas.querySelectorAll(".table-card");
      for (const card of cards) {
        if (card.dataset.table === tableName) return card;
      }
      return null;
    }

    function positionCard(card, x, y) {
      card.style.left = `${Math.round(x)}px`;
      card.style.top = `${Math.round(y)}px`;
    }

    function attachDrag(card, canvas, edgeLayer) {
      const head = card.querySelector(".table-head");
      if (!head) return;
      const tableName = card.dataset.table;
      let dragging = false;
      let offsetX = 0;
      let offsetY = 0;

      const onMove = (event) => {
        if (!dragging) return;
        const canvasRect = canvas.getBoundingClientRect();
        const scrollParent = canvas.parentElement;
        const scrollLeft = scrollParent?.scrollLeft || 0;
        const scrollTop = scrollParent?.scrollTop || 0;
        const maxX = Math.max(0, canvas.clientWidth - card.offsetWidth - 8);
        const maxY = Math.max(0, canvas.clientHeight - card.offsetHeight - 8);
        const x = clamp(event.clientX - canvasRect.left + scrollLeft - offsetX, 8, maxX);
        const y = clamp(event.clientY - canvasRect.top + scrollTop - offsetY, 8, maxY);
        positionCard(card, x, y);
        state.tablePositions[tableName] = { x, y };
        drawEdges(state.currentRelationships, canvas, edgeLayer);
      };

      const onUp = () => {
        if (!dragging) return;
        dragging = false;
        head.classList.remove("dragging");
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
        document.removeEventListener("pointercancel", onUp);
      };

      head.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        dragging = true;
        head.classList.add("dragging");
        const cardRect = card.getBoundingClientRect();
        offsetX = event.clientX - cardRect.left;
        offsetY = event.clientY - cardRect.top;
        document.addEventListener("pointermove", onMove);
        document.addEventListener("pointerup", onUp);
        document.addEventListener("pointercancel", onUp);
        event.preventDefault();
      });
    }

    function updateVisibleJoinCount(relationships) {
      const el = document.getElementById("visibleJoinCount");
      if (el) el.textContent = String(relationships.length);
    }

    function autoLayoutTables() {
      const matching = refreshMatchingTables();
      const tableDegree = new Map();
      activeRelationships().forEach((join) => {
        tableDegree.set(join.left_table, (tableDegree.get(join.left_table) || 0) + 1);
        tableDegree.set(join.right_table, (tableDegree.get(join.right_table) || 0) + 1);
      });
      const ordered = [...state.payload.tables]
        .filter((table) => matching.size === 0 || matching.has(table.name))
        .sort((a, b) => {
          const da = tableDegree.get(a.name) || 0;
          const db = tableDegree.get(b.name) || 0;
          if (db !== da) return db - da;
          return a.name.localeCompare(b.name);
        });
      ordered.forEach((table, idx) => {
        state.tablePositions[table.name] = layoutPosition(idx, ordered.length);
      });
    }

    function fitVisibleTables() {
      const view = document.getElementById("diagramView");
      const canvas = document.getElementById("diagramCanvas");
      const cards = [...canvas.querySelectorAll(".table-card:not(.dimmed)")];
      if (cards.length === 0) return;

      let minX = Number.POSITIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      cards.forEach((card) => {
        minX = Math.min(minX, card.offsetLeft);
        minY = Math.min(minY, card.offsetTop);
        maxX = Math.max(maxX, card.offsetLeft + card.offsetWidth);
        maxY = Math.max(maxY, card.offsetTop + card.offsetHeight);
      });

      const targetX = Math.max(0, minX - 60);
      const targetY = Math.max(0, minY - 60);
      const targetCenterX = targetX + (maxX - minX) / 2;
      const targetCenterY = targetY + (maxY - minY) / 2;
      const scrollLeft = Math.max(0, targetCenterX - view.clientWidth / 2);
      const scrollTop = Math.max(0, targetCenterY - view.clientHeight / 2);
      view.scrollTo({ left: scrollLeft, top: scrollTop, behavior: "smooth" });
    }

    function renderDiagram() {
      const canvas = document.getElementById("diagramCanvas");
      const edgeLayer = document.getElementById("edgeLayer");
      canvas.querySelectorAll(".table-card").forEach((el) => el.remove());
      const joins = activeRelationships();
      state.currentRelationships = joins;
      updateVisibleJoinCount(joins);
      const colsByTable = relationshipColumnsByTable();
      const matchingTables = refreshMatchingTables();

      state.payload.tables.forEach((table, index) => {
        const card = buildCard(table, colsByTable.get(table.name));
        const pos = state.tablePositions[table.name] || layoutPosition(index, state.payload.tables.length);
        state.tablePositions[table.name] = pos;
        positionCard(card, pos.x, pos.y);
        if (state.tableQuery.trim() && !matchingTables.has(table.name)) {
          card.classList.add("dimmed");
        }
        canvas.appendChild(card);
        attachDrag(card, canvas, edgeLayer);
      });
      requestAnimationFrame(() => drawEdges(joins, canvas, edgeLayer));
    }

    function renderTableSelect() {
      const select = document.getElementById("tableSelect");
      select.innerHTML = "";
      state.payload.tables.forEach((table) => {
        const option = document.createElement("option");
        option.value = table.name;
        option.textContent = table.name;
        select.appendChild(option);
      });
      select.addEventListener("change", renderTablePreview);
      renderTablePreview();
    }

    function renderTablePreview() {
      const tableName = document.getElementById("tableSelect").value;
      const table = tableByName(tableName);
      const meta = document.getElementById("tableMeta");
      const target = document.getElementById("tablePreview");
      if (!table) return;

      meta.textContent = `${table.row_count.toLocaleString()} rows, showing ${table.sample_rows.length} sample rows`;
      const columns = table.columns.map((c) => c.name);
      const rows = table.sample_rows;
      const html = [
        `<table class="preview"><thead><tr>${columns.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`,
        rows.map((row) =>
          `<tr>${columns.map((c) => `<td>${(row[c] ?? "").toString().replace(/</g, "&lt;")}</td>`).join("")}</tr>`
        ).join(""),
        "</tbody></table>",
      ].join("");
      target.innerHTML = html;
    }

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }

    function listHtml(items) {
      if (!items || items.length === 0) return "<div class='hint'>None</div>";
      return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
    }

    function relationKey(left, right) {
      return [left, right].sort().join(" :: ");
    }

    function parseJoinText(value) {
      if (typeof value !== "string") return null;
      const text = value.trim();
      const separator = text.includes("<->") ? "<->" : (text.includes("=>") ? "=>" : "->");
      if (!text.includes(separator)) return null;
      const parts = text.split(separator);
      if (parts.length < 2) return null;
      const left = parts[0].trim();
      const right = parts.slice(1).join(separator).trim();
      if (!left || !right) return null;
      return { left, right };
    }

    function collectExpectedJoins(manifest, coreRelations) {
      const expected = new Map();

      function pushRefs(leftRef, rightRef, guess) {
        const left = splitRef(leftRef);
        const right = splitRef(rightRef);
        if (!left.table || !left.column || !right.table || !right.column) return;
        const leftRefClean = `${left.table}.${left.column}`;
        const rightRefClean = `${right.table}.${right.column}`;
        const key = relationKey(leftRefClean, rightRefClean);
        if (expected.has(key)) return;
        expected.set(key, {
          display: joinDisplay(leftRefClean, rightRefClean),
          left_table: left.table,
          left_column: left.column,
          right_table: right.table,
          right_column: right.column,
          relationship_guess: guess || "ground_truth",
        });
      }

      (coreRelations || []).forEach((rel) => {
        if (!rel || typeof rel !== "object") return;
        const left = `${String(rel.from_table || rel.fromTable || "").trim()}.${String(rel.from_column || rel.fromColumn || "").trim()}`;
        const right = `${String(rel.to_table || rel.toTable || "").trim()}.${String(rel.to_column || rel.toColumn || "").trim()}`;
        if (left.includes("undefined") || right.includes("undefined")) return;
        pushRefs(left, right, rel.relationship_guess || rel.relationship || "ground_truth");
      });
      ((manifest && manifest.expected_joins) || []).forEach((item) => {
        if (typeof item === "object" && item !== null) {
          const left = `${String(item.from_table || item.fromTable || "").trim()}.${String(item.from_column || item.fromColumn || "").trim()}`;
          const right = `${String(item.to_table || item.toTable || "").trim()}.${String(item.to_column || item.toColumn || "").trim()}`;
          if (left.includes("undefined") || right.includes("undefined")) return;
          pushRefs(left, right, item.relationship_guess || item.relationship || "ground_truth");
          return;
        }
        const parsed = parseJoinText(String(item));
        if (!parsed) return;
        pushRefs(parsed.left, parsed.right, "ground_truth");
      });
      return expected;
    }

    function renderGroundTruth() {
      const manifest = state.payload.manifest;
      const setRail = (id, items) => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = listHtml(items);
      };
      const setMetric = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = String(value);
      };

      setMetric("covThreshold", state.threshold.toFixed(2));
      const predictedJoins = state.payload.report.joins || [];
      const predictedAtThreshold = predictedJoins.filter(
        (join) => Number(join.confidence || 0) >= state.threshold
      );
      if (!manifest) {
        const predictedMap = new Map();
        predictedAtThreshold.forEach((join) => {
          const left = `${join.left_table}.${join.left_column}`;
          const right = `${join.right_table}.${join.right_column}`;
          predictedMap.set(relationKey(left, right), joinDisplay(left, right));
        });
        setMetric("covExpected", 0);
        setMetric("covPredicted", predictedMap.size);
        setMetric("covFound", predictedMap.size);
        setMetric("covMissing", 0);
        setMetric("covUnexpected", 0);
        setMetric("covRecall", "0.0%");
        setMetric("covPrecision", "0.0%");
        const noManifest = ["No manifest.json found in analyzed folder."];
        setRail("joinsFoundList", predictedMap.size ? sortStrings(Array.from(predictedMap.values())) : noManifest);
        setRail("missingJoinsList", noManifest);
        setRail("unexpectedJoinsList", noManifest);
        state.relationshipPool = buildRelationshipPool(new Map(), predictedAtThreshold, false);
        return;
      }

      const ground = manifest.ground_truth || {};
      const coreRelations = ground.core_relationships || ground.core_relationshpis || [];
      const expectedMap = collectExpectedJoins(manifest, coreRelations);
      state.relationshipPool = buildRelationshipPool(expectedMap, predictedAtThreshold, true);
      const predictedMap = new Map();
      predictedAtThreshold.forEach((join) => {
        const left = `${join.left_table}.${join.left_column}`;
        const right = `${join.right_table}.${join.right_column}`;
        predictedMap.set(relationKey(left, right), joinDisplay(left, right));
      });
      const expectedKeys = new Set(expectedMap.keys());
      const predictedKeys = new Set(predictedMap.keys());
      const found = Array.from(expectedMap.entries())
        .filter(([key]) => predictedKeys.has(key))
        .map(([, info]) => info.display);
      const missing = Array.from(expectedMap.entries())
        .filter(([key]) => !predictedKeys.has(key))
        .map(([, info]) => info.display);
      const unexpected = Array.from(predictedMap.entries())
        .filter(([key]) => !expectedKeys.has(key))
        .map(([, label]) => label);

      const recall = expectedMap.size === 0 ? 0 : found.length / expectedMap.size;
      const precision = predictedMap.size === 0 ? 0 : found.length / predictedMap.size;

      setMetric("covExpected", expectedMap.size);
      setMetric("covPredicted", predictedMap.size);
      setMetric("covFound", found.length);
      setMetric("covMissing", missing.length);
      setMetric("covUnexpected", unexpected.length);
      setMetric("covRecall", `${(recall * 100).toFixed(1)}%`);
      setMetric("covPrecision", `${(precision * 100).toFixed(1)}%`);

      setRail("joinsFoundList", sortStrings(found));
      setRail("missingJoinsList", sortStrings(missing));
      setRail("unexpectedJoinsList", sortStrings(unexpected));
    }

    async function init() {
      const embedded = document.getElementById("smartjoinEmbeddedData");
      const embeddedText = embedded?.textContent?.trim() || "";
      if (embeddedText) {
        state.payload = JSON.parse(embeddedText);
      } else {
        const response = await fetch("data.json");
        state.payload = await response.json();
      }
      const slider = document.getElementById("confidenceRange");
      const label = document.getElementById("confidenceLabel");
      const searchInput = document.getElementById("tableSearch");
      const edgeModeSelect = document.getElementById("edgeMode");
      const relayoutBtn = document.getElementById("relayoutBtn");
      const fitViewBtn = document.getElementById("fitViewBtn");
      const clearFilterBtn = document.getElementById("clearFilterBtn");
      slider.value = String(state.payload.meta.min_confidence ?? 0.75);
      state.threshold = Number(slider.value);
      label.textContent = Number(slider.value).toFixed(2);
      slider.addEventListener("input", () => {
        state.threshold = Number(slider.value);
        label.textContent = Number(slider.value).toFixed(2);
        state.selectedRelationshipKey = null;
        renderGroundTruth();
        renderTableList();
        renderDiagram();
      });
      searchInput.addEventListener("input", () => {
        state.tableQuery = searchInput.value || "";
        state.selectedRelationshipKey = null;
        renderGroundTruth();
        renderTableList();
        renderDiagram();
      });
      edgeModeSelect.addEventListener("change", () => {
        state.edgeMode = edgeModeSelect.value || "all";
        state.selectedRelationshipKey = null;
        renderGroundTruth();
        renderDiagram();
      });
      relayoutBtn.addEventListener("click", () => {
        autoLayoutTables();
        renderDiagram();
        fitVisibleTables();
      });
      fitViewBtn.addEventListener("click", () => {
        fitVisibleTables();
      });
      clearFilterBtn.addEventListener("click", () => {
        state.tableQuery = "";
        state.edgeMode = "all";
        state.selectedRelationshipKey = null;
        searchInput.value = "";
        edgeModeSelect.value = "all";
        renderGroundTruth();
        renderTableList();
        renderDiagram();
      });

      window.addEventListener("resize", () => {
        const canvas = document.getElementById("diagramCanvas");
        const edgeLayer = document.getElementById("edgeLayer");
        drawEdges(state.currentRelationships, canvas, edgeLayer);
      });

      renderGroundTruth();
      renderTableList();
      renderTableSelect();
      autoLayoutTables();
      renderDiagram();
      fitVisibleTables();
    }

    init().catch((err) => {
      document.body.innerHTML = `<pre style="padding:16px;color:#7a2415">Failed to load debug data: ${err}</pre>`;
    });
  </script>
</body>
</html>
"""


def build_debug_site(
    path: Path,
    out_dir: Path,
    sample_rows: int = 10_000,
    sample_seed: int = 42,
    preview_rows: int = 25,
    max_tables: int | None = None,
    max_columns: int | None = None,
    min_confidence: float = 0.75,
    graph_top_k_per_pair: int = 3,
    distinct_low_card_threshold: int = 64,
    near_unique_threshold: float = 0.90,
    date_caps: dict[str, float] | None = None,
    fast_profile: bool = False,
    profile_entropy_cap: int = 50_000,
    join_weights: dict[str, float] | None = None,
    xlsx_sheet_map: dict[str, str] | None = None,
    json_flatten_depth: int = 1,
    llm_enabled: bool = False,
    llm_plugin: str | None = None,
    precomputed_report: AnalysisReport | None = None,
) -> tuple[Path, Path]:
    """Generate debug site artifacts `(index_path, data_path)`."""
    payload = _build_payload(
        path=path,
        sample_rows=sample_rows,
        sample_seed=sample_seed,
        preview_rows=preview_rows,
        max_tables=max_tables,
        max_columns=max_columns,
        min_confidence=min_confidence,
        graph_top_k_per_pair=graph_top_k_per_pair,
        distinct_low_card_threshold=distinct_low_card_threshold,
        near_unique_threshold=near_unique_threshold,
        date_caps=date_caps,
        fast_profile=fast_profile,
        profile_entropy_cap=profile_entropy_cap,
        join_weights=join_weights,
        xlsx_sheet_map=xlsx_sheet_map,
        json_flatten_depth=json_flatten_depth,
        llm_enabled=llm_enabled,
        llm_plugin=llm_plugin,
        precomputed_report=precomputed_report,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.html"
    data_path = out_dir / "data.json"
    payload_json = json.dumps(_jsonable(payload), indent=2, allow_nan=False)
    embedded_payload = payload_json.replace("</", "<\\/")
    rendered_html = DEBUG_SITE_HTML.replace("__SMARTJOIN_EMBEDDED_DATA__", embedded_payload)
    index_path.write_text(rendered_html, encoding="utf-8")
    data_path.write_text(payload_json, encoding="utf-8")
    return index_path, data_path
