"""Static debug site generator for relationship inspection."""

# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from alchemia.analysis import analyze_path
from alchemia.ingestion import load_tables
from alchemia.models import AnalysisReport


def _jsonable(value: Any) -> Any:
    """Convert a Python value to JSON-safe representation."""
    if isinstance(value, (str, int, float, bool)) or value is None:
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


def _build_payload(
    path: Path,
    sample_rows: int,
    sample_seed: int,
    preview_rows: int,
    max_tables: int | None,
    max_columns: int | None,
    min_confidence: float,
    graph_top_k_per_pair: int,
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

    return {
        "meta": {
            "source_path": str(path.resolve()),
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "preview_rows": preview_rows,
            "sample_rows": sample_rows,
            "sample_seed": sample_seed,
            "min_confidence": min_confidence,
            "graph_top_k_per_pair": graph_top_k_per_pair,
            "fast_profile": fast_profile,
            "profile_entropy_cap": profile_entropy_cap,
        },
        "manifest": manifest,
        "report": report.model_dump(mode="json"),
        "tables": table_payload,
    }


DEBUG_SITE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Alchemia Debug Viewer</title>
  <style>
    :root{
      --bg:#f4f0e8;
      --panel:#fffaf1;
      --ink:#1a252f;
      --muted:#5f6b76;
      --edge:#d26a3a;
      --edge-true:#22985f;
      --edge-false:#cf4457;
      --accent:#117a8b;
      --accent-soft:#dbf4f8;
      --card:#fffef9;
      --border:#d9cec1;
      --shadow:0 14px 30px rgba(28, 37, 46, 0.08);
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      font-family:"Sora","IBM Plex Sans","Segoe UI",sans-serif;
      color:var(--ink);
      background:
        radial-gradient(circle at 8% 8%, #fff6d5, transparent 35%),
        radial-gradient(circle at 88% 0%, #dbeff6, transparent 42%),
        linear-gradient(120deg, #f5efe6 0%, #eef5f4 100%);
      min-height:100vh;
    }
    .shell{
      display:grid;
      grid-template-columns:300px 1fr;
      min-height:100vh;
    }
    .sidebar{
      border-right:1px solid var(--border);
      background:rgba(255,250,241,0.92);
      backdrop-filter:blur(8px);
      padding:18px 16px;
      overflow:auto;
    }
    .brand{
      margin:0 0 6px 0;
      font-size:1.2rem;
      letter-spacing:0.03em;
    }
    .sub{
      margin:0 0 16px 0;
      color:var(--muted);
      font-size:0.86rem;
      line-height:1.4;
    }
    .panel{
      background:var(--panel);
      border:1px solid var(--border);
      border-radius:12px;
      padding:12px;
      margin-bottom:14px;
      box-shadow:var(--shadow);
    }
    .panel h3{
      margin:0 0 8px 0;
      font-size:0.86rem;
      text-transform:uppercase;
      letter-spacing:0.08em;
      color:var(--muted);
    }
    .tabs{
      display:flex;
      gap:8px;
      margin-bottom:12px;
      flex-wrap:wrap;
    }
    .tab{
      border:1px solid var(--border);
      background:white;
      color:var(--ink);
      border-radius:999px;
      padding:6px 12px;
      cursor:pointer;
      font-size:0.84rem;
    }
    .tab.active{
      background:var(--accent);
      color:white;
      border-color:var(--accent);
    }
    .control-label{
      display:block;
      font-size:0.78rem;
      color:var(--muted);
      margin-bottom:6px;
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
      background:white;
      border-radius:10px;
      padding:8px;
      color:var(--ink);
      cursor:pointer;
      font-size:0.83rem;
    }
    .main{
      padding:18px;
      overflow:hidden;
      display:flex;
      flex-direction:column;
      gap:14px;
    }
    .canvas-wrap{
      position:relative;
      border:1px solid var(--border);
      background:rgba(255,255,255,0.86);
      border-radius:16px;
      box-shadow:var(--shadow);
      min-height:680px;
      overflow:auto;
    }
    .diagram-canvas{
      position:relative;
      width:1800px;
      height:1200px;
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
      stroke-width:1.8;
      opacity:0.62;
      pointer-events:stroke;
      cursor:pointer;
    }
    .edge-layer path:hover{
      opacity:1;
      stroke-width:2.6;
    }
    .table-card{
      position:absolute;
      width:280px;
      background:var(--card);
      border:1px solid var(--border);
      border-radius:14px;
      box-shadow:var(--shadow);
      overflow:hidden;
      z-index:3;
    }
    .table-head{
      background:linear-gradient(120deg,#eef9f7 0%,#fdf6e8 100%);
      border-bottom:1px solid var(--border);
      padding:10px 12px;
      cursor:grab;
      user-select:none;
      touch-action:none;
    }
    .table-head.dragging{cursor:grabbing}
    .table-head h4{
      margin:0;
      font-size:0.9rem;
    }
    .table-head span{
      color:var(--muted);
      font-size:0.76rem;
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
      padding:6px 10px;
      border-bottom:1px dashed #ebe0d4;
      font-family:"IBM Plex Mono","Fira Code","Consolas",monospace;
      font-size:0.74rem;
    }
    .column-list li.join-col{
      background:var(--accent-soft);
      color:#0e5762;
      font-weight:600;
    }
    .data-grid,.truth-grid{
      border:1px solid var(--border);
      border-radius:16px;
      background:rgba(255,255,255,0.9);
      box-shadow:var(--shadow);
      display:none;
      flex-direction:column;
      min-height:680px;
      overflow:hidden;
    }
    .data-grid.active,.truth-grid.active,.canvas-wrap.active{display:flex}
    .canvas-wrap.active{display:block}
    .data-toolbar{
      display:flex;
      gap:10px;
      padding:12px;
      border-bottom:1px solid var(--border);
      align-items:center;
      flex-wrap:wrap;
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
      border-collapse:collapse;
      width:100%;
      min-width:760px;
      background:white;
    }
    table.preview th,table.preview td{
      border:1px solid #e8dfd4;
      padding:6px 8px;
      font-size:0.78rem;
      text-align:left;
      white-space:nowrap;
    }
    table.preview th{
      position:sticky;
      top:0;
      background:#f8f3ea;
      z-index:2;
    }
    .hint{
      font-size:0.78rem;
      color:var(--muted);
      line-height:1.45;
    }
    .truth-badge{
      display:inline-block;
      border-radius:999px;
      padding:2px 8px;
      font-size:0.72rem;
      font-weight:700;
      letter-spacing:0.02em;
      margin-bottom:6px;
    }
    .truth-badge.true{
      background:#e3f6eb;
      color:#1f7f4e;
      border:1px solid #93d5ae;
    }
    .truth-badge.false{
      background:#fde9eb;
      color:#9e2f3c;
      border:1px solid #efb3bb;
    }
    @media (max-width:1200px){
      .shell{grid-template-columns:1fr}
      .sidebar{border-right:0;border-bottom:1px solid var(--border)}
      .main{padding:12px}
      .diagram-canvas{width:1300px;height:1000px}
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <h1 class="brand">Alchemia Debug Viewer</h1>
      <p class="sub">Relationship map and table previews for debugging inference output.</p>
      <div class="tabs">
        <button class="tab active" id="tabDiagram">Relationship Map</button>
        <button class="tab" id="tabData">Table Samples</button>
        <button class="tab" id="tabTruth">Ground Truth</button>
      </div>
      <section class="panel">
        <h3>Filter</h3>
        <label class="control-label" for="confidenceRange">Min confidence</label>
        <input id="confidenceRange" type="range" min="0" max="1" step="0.01" value="0.75">
        <div class="hint">Current threshold: <strong id="confidenceLabel">0.75</strong></div>
      </section>
      <section class="panel">
        <h3>Tables</h3>
        <ul id="tableList" class="table-list"></ul>
      </section>
      <section class="panel">
        <h3>Selected Relationship</h3>
        <div id="relationDetails" class="hint">Click a connection line to inspect details.</div>
      </section>
    </aside>
    <main class="main">
      <section id="diagramView" class="canvas-wrap active">
        <div id="diagramCanvas" class="diagram-canvas">
          <svg id="edgeLayer" class="edge-layer"></svg>
        </div>
      </section>
      <section id="dataView" class="data-grid">
        <div class="data-toolbar">
          <label class="control-label" for="tableSelect">Table</label>
          <select id="tableSelect"></select>
          <span class="hint" id="tableMeta"></span>
        </div>
        <div id="tablePreview" class="table-preview"></div>
      </section>
      <section id="truthView" class="truth-grid">
        <div id="truthContent" class="truth-content"></div>
      </section>
    </main>
  </div>
  <script id="alchemiaEmbeddedData" type="application/json">__ALCHEMIA_EMBEDDED_DATA__</script>
  <script>
    const state = {
      payload: null,
      threshold: 0.75,
      tablePositions: {},
      currentRelationships: [],
      expectedJoinKeys: new Set(),
    };

    const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

    function tableByName(name) {
      return state.payload.tables.find((t) => t.name === name);
    }

    function activeRelationships() {
      return state.payload.report.joins.filter((j) => j.confidence >= state.threshold);
    }

    function joinDisplay(left, right) {
      return `${left} -> ${right}`;
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
      state.payload.tables.forEach((table) => {
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
        if (!leftEl || !rightEl) return;

        const a = leftEl.getBoundingClientRect();
        const b = rightEl.getBoundingClientRect();
        const x1 = a.right - rect.left;
        const y1 = a.top + a.height / 2 - rect.top;
        const x2 = b.left - rect.left;
        const y2 = b.top + b.height / 2 - rect.top;
        const bend = clamp((x2 - x1) * 0.5, 60, 220);
        const leftRef = `${rel.left_table}.${rel.left_column}`;
        const rightRef = `${rel.right_table}.${rel.right_column}`;
        const relKey = relationKey(leftRef, rightRef);
        const hasGroundTruth = state.expectedJoinKeys.size > 0;
        const isTrue = hasGroundTruth && state.expectedJoinKeys.has(relKey);
        const isFalse = hasGroundTruth && !isTrue;

        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`);
        path.setAttribute("stroke-opacity", String(clamp(rel.confidence, 0.25, 1)));
        if (isTrue) {
          path.setAttribute("stroke", "var(--edge-true)");
        } else if (isFalse) {
          path.setAttribute("stroke", "var(--edge-false)");
        } else {
          path.setAttribute("stroke", "var(--edge)");
        }
        path.dataset.edge = JSON.stringify(rel);
        path.style.pointerEvents = "stroke";
        path.addEventListener("click", () => {
          const details = document.getElementById("relationDetails");
          const signals = Object.entries(rel.breakdown.signals || {})
            .map(([k, v]) => `${k}: ${Number(v).toFixed(3)}`)
            .join("<br>");
          const truthBadge = hasGroundTruth
            ? `<span class="truth-badge ${isTrue ? "true" : "false"}">${isTrue ? "TRUE relationship" : "FALSE relationship"}</span><br>`
            : "";
          details.innerHTML = `
            ${truthBadge}
            <strong>${rel.left_table}.${rel.left_column}</strong> -> <strong>${rel.right_table}.${rel.right_column}</strong><br>
            confidence: <strong>${rel.confidence.toFixed(3)}</strong><br>
            relationship: ${rel.relationship_guess}<br><br>
            ${signals}
          `;
        });
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

    function renderDiagram() {
      const canvas = document.getElementById("diagramCanvas");
      const edgeLayer = document.getElementById("edgeLayer");
      canvas.querySelectorAll(".table-card").forEach((el) => el.remove());
      const joins = activeRelationships();
      state.currentRelationships = joins;
      const colsByTable = relationshipColumnsByTable();

      state.payload.tables.forEach((table, index) => {
        const card = buildCard(table, colsByTable.get(table.name));
        const pos = state.tablePositions[table.name] || layoutPosition(index, state.payload.tables.length);
        state.tablePositions[table.name] = pos;
        positionCard(card, pos.x, pos.y);
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
      (coreRelations || []).forEach((rel) => {
        if (!rel || typeof rel !== "object") return;
        const left = `${rel.from_table}.${rel.from_column}`;
        const right = `${rel.to_table}.${rel.to_column}`;
        if (left.includes("undefined") || right.includes("undefined")) return;
        expected.set(relationKey(left, right), joinDisplay(left, right));
      });
      ((manifest && manifest.expected_joins) || []).forEach((item) => {
        if (typeof item === "object" && item !== null) {
          const left = `${item.from_table}.${item.from_column}`;
          const right = `${item.to_table}.${item.to_column}`;
          if (left.includes("undefined") || right.includes("undefined")) return;
          expected.set(relationKey(left, right), joinDisplay(left, right));
          return;
        }
        const parsed = parseJoinText(String(item));
        if (!parsed) return;
        expected.set(relationKey(parsed.left, parsed.right), joinDisplay(parsed.left, parsed.right));
      });
      return expected;
    }

    function formatCompositeKey(item) {
      if (typeof item === "string") return item.trim();
      if (!item || typeof item !== "object") return "";
      const table = String(item.table || item.table_name || "").trim();
      const columns = Array.isArray(item.columns) ? item.columns.map((x) => String(x).trim()).filter(Boolean) : [];
      if (!table || columns.length === 0) return "";
      return `${table}(${columns.join(", ")})`;
    }

    function collectCompositeKeys(manifest, ground) {
      const out = [];
      ((manifest && manifest.expected_composite_keys) || []).forEach((item) => {
        const label = formatCompositeKey(item);
        if (label) out.push(label);
      });
      ((ground && ground.composite_key_candidates) || []).forEach((item) => {
        const label = formatCompositeKey(item);
        if (label) out.push(label);
      });
      return dedupeStrings(out);
    }

    function collectTrapColumns(manifest, ground) {
      const traps = (ground && ground.traps) || {};
      const out = []
        .concat((manifest && manifest.trap_columns) || [])
        .concat(traps.shared_low_cardinality_columns || [])
        .concat(traps.date_like_columns || []);
      return dedupeStrings(out);
    }

    function collectOverlapTraps(ground) {
      const traps = (ground && ground.traps && ground.traps.overlapping_value_traps) || [];
      const out = [];
      traps.forEach((trap) => {
        if (!trap || typeof trap !== "object") return;
        const columns = Array.isArray(trap.columns)
          ? trap.columns.map((col) => String(col).trim()).filter(Boolean).join(" <-> ")
          : String(trap.columns || "").trim();
        if (!columns) return;
        const overlap = trap.expected_overlap ? ` (${String(trap.expected_overlap).trim()})` : "";
        const reason = trap.reason ? ` - ${String(trap.reason).trim()}` : "";
        out.push(`${columns}${overlap}${reason}`);
      });
      return dedupeStrings(out);
    }

    function collectMisleadingNameTraps(ground) {
      const traps = (ground && ground.traps && ground.traps.misleading_name_pairs) || [];
      const out = [];
      traps.forEach((pair) => {
        if (!pair || typeof pair !== "object") return;
        const left = String(pair.left || "").trim();
        const right = String(pair.right || "").trim();
        if (!left || !right) return;
        const reason = pair.reason ? ` - ${String(pair.reason).trim()}` : "";
        out.push(`${left} vs ${right}${reason}`);
      });
      return dedupeStrings(out);
    }

    function refreshExpectedJoinKeys() {
      const manifest = state.payload?.manifest;
      if (!manifest) {
        state.expectedJoinKeys = new Set();
        return;
      }
      const ground = manifest.ground_truth || {};
      const coreRelations = ground.core_relationships || ground.core_relationshpis || [];
      const expectedMap = collectExpectedJoins(manifest, coreRelations);
      state.expectedJoinKeys = new Set(expectedMap.keys());
    }

    function renderGroundTruth() {
      const host = document.getElementById("truthContent");
      const manifest = state.payload.manifest;
      if (!manifest) {
        state.expectedJoinKeys = new Set();
        host.innerHTML = `<article class="truth-card"><h4>Ground Truth</h4><div class="hint">No manifest.json found in analyzed folder.</div></article>`;
        return;
      }

      const ground = manifest.ground_truth || {};
      const coreRelations = ground.core_relationships || ground.core_relationshpis || [];
      const expectedMap = collectExpectedJoins(manifest, coreRelations);
      state.expectedJoinKeys = new Set(expectedMap.keys());

      const predictedMap = new Map();
      activeRelationships().forEach((join) => {
        const left = `${join.left_table}.${join.left_column}`;
        const right = `${join.right_table}.${join.right_column}`;
        predictedMap.set(relationKey(left, right), joinDisplay(left, right));
      });

      const expectedKeys = new Set(expectedMap.keys());
      const predictedKeys = new Set(predictedMap.keys());
      const found = Array.from(expectedMap.entries())
        .filter(([key]) => predictedKeys.has(key))
        .map(([, label]) => label);
      const missing = Array.from(expectedMap.entries())
        .filter(([key]) => !predictedKeys.has(key))
        .map(([, label]) => label);
      const unexpected = Array.from(predictedMap.entries())
        .filter(([key]) => !expectedKeys.has(key))
        .map(([, label]) => label);
      const predictedList = Array.from(predictedMap.values());

      const recall = expectedMap.size === 0 ? 0 : found.length / expectedMap.size;
      const precision = predictedMap.size === 0 ? 0 : found.length / predictedMap.size;
      const compositeKeys = collectCompositeKeys(manifest, ground);
      const trapColumns = collectTrapColumns(manifest, ground);
      const overlapTrapLines = collectOverlapTraps(ground);
      const misleadingLines = collectMisleadingNameTraps(ground);

      host.innerHTML = `
        <article class="truth-card">
          <h4>Coverage</h4>
          <div class="truth-stat">Expected joins: <strong>${expectedMap.size}</strong></div>
          <div class="truth-stat">Predicted joins: <strong>${predictedMap.size}</strong></div>
          <div class="truth-stat">Found joins: <strong>${found.length}</strong></div>
          <div class="truth-stat">Recall: <strong>${(recall * 100).toFixed(1)}%</strong></div>
          <div class="truth-stat">Precision: <strong>${(precision * 100).toFixed(1)}%</strong></div>
          <div class="truth-stat">Missing joins: ${missing.length}</div>
          <div class="truth-stat">Unexpected joins: ${unexpected.length}</div>
          <div class="hint">Using current confidence threshold: ${state.threshold.toFixed(2)}</div>
        </article>
        <article class="truth-card">
          <h4>Expected Joins</h4>
          ${listHtml(Array.from(expectedMap.values()))}
        </article>
        <article class="truth-card">
          <h4>Joins Found</h4>
          ${listHtml(predictedList)}
        </article>
        <article class="truth-card">
          <h4>Missing Joins</h4>
          ${listHtml(missing)}
        </article>
        <article class="truth-card">
          <h4>Joins Found But Shouldn't Be</h4>
          ${listHtml(unexpected)}
        </article>
        <article class="truth-card">
          <h4>Expected Composite Keys</h4>
          ${listHtml(compositeKeys)}
        </article>
        <article class="truth-card">
          <h4>Trap Columns</h4>
          ${listHtml(trapColumns)}
        </article>
        <article class="truth-card">
          <h4>Overlap Traps</h4>
          ${listHtml(overlapTrapLines)}
        </article>
        <article class="truth-card">
          <h4>Misleading Name Traps</h4>
          ${listHtml(misleadingLines)}
        </article>
      `;
    }

    function setActiveView(view) {
      const tabIds = ["tabDiagram", "tabData", "tabTruth"];
      const viewIds = ["diagramView", "dataView", "truthView"];
      tabIds.forEach((id) => document.getElementById(id).classList.remove("active"));
      viewIds.forEach((id) => document.getElementById(id).classList.remove("active"));
      document.getElementById(`tab${view}`).classList.add("active");
      document.getElementById(`${view.toLowerCase()}View`).classList.add("active");
    }

    function switchToDiagram() {
      setActiveView("Diagram");
    }

    function switchToData() {
      setActiveView("Data");
    }

    function switchToTruth() {
      renderGroundTruth();
      setActiveView("Truth");
    }

    async function init() {
      const embedded = document.getElementById("alchemiaEmbeddedData");
      const embeddedText = embedded?.textContent?.trim() || "";
      if (embeddedText) {
        state.payload = JSON.parse(embeddedText);
      } else {
        const response = await fetch("data.json");
        state.payload = await response.json();
      }
      refreshExpectedJoinKeys();
      const slider = document.getElementById("confidenceRange");
      const label = document.getElementById("confidenceLabel");
      slider.value = String(state.payload.meta.min_confidence ?? 0.75);
      state.threshold = Number(slider.value);
      label.textContent = Number(slider.value).toFixed(2);
      slider.addEventListener("input", () => {
        state.threshold = Number(slider.value);
        label.textContent = Number(slider.value).toFixed(2);
        renderDiagram();
        renderGroundTruth();
      });

      window.addEventListener("resize", () => {
        const canvas = document.getElementById("diagramCanvas");
        const edgeLayer = document.getElementById("edgeLayer");
        drawEdges(state.currentRelationships, canvas, edgeLayer);
      });

      document.getElementById("tabDiagram").addEventListener("click", switchToDiagram);
      document.getElementById("tabData").addEventListener("click", switchToData);
      document.getElementById("tabTruth").addEventListener("click", switchToTruth);

      renderTableList();
      renderTableSelect();
      renderDiagram();
      renderGroundTruth();
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
    payload_json = json.dumps(payload, indent=2)
    embedded_payload = payload_json.replace("</", "<\\/")
    rendered_html = DEBUG_SITE_HTML.replace("__ALCHEMIA_EMBEDDED_DATA__", embedded_payload)
    index_path.write_text(rendered_html, encoding="utf-8")
    data_path.write_text(payload_json, encoding="utf-8")
    return index_path, data_path

