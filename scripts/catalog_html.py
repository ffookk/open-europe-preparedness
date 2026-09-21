"""Render and safely save a self-contained catalog; no network or browser storage."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
from pathlib import Path

from .catalog import Catalog, CatalogError, DATE_FIELDS, FACET_FIELDS, NOTICE, SORT_FIELDS

CSS = r"""
:root {color-scheme:light;--ink:#172e38;--muted:#4c6370;--accent:#126b64;--line:#cbd8dc;--paper:#fff;--wash:#edf3f2}
* {box-sizing:border-box} body {margin:0;background:var(--wash);color:var(--ink);font:16px/1.6 system-ui,sans-serif}
header {background:#163b42;color:#fff;padding:2.8rem max(5vw,1rem) 2rem} header p {max-width:72ch;color:#deeeeb;margin:.6rem 0}
h1 {font-size:clamp(1.9rem,4vw,3rem);line-height:1.15;margin:.4rem 0 1rem} h2 {font-size:1.25rem;margin:.2rem 0 .8rem} h3 {font-size:1.1rem}
.kicker {text-transform:uppercase;font-size:.75rem;letter-spacing:.16em;font-weight:700}.cutoff {font-family:ui-monospace,monospace}
main {max-width:1500px;margin:auto;padding:1.5rem;display:grid;grid-template-columns:290px minmax(0,1fr);gap:1.5rem}
.panel,.card {background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:1.2rem}.filters {align-self:start}
label {display:block;font-size:.85rem;font-weight:650;margin:.8rem 0 .25rem} input,select,button {font:inherit;border-radius:6px}
input:not([type=checkbox]),select {width:100%;padding:.55rem;border:1px solid #839ba4;background:#fff;color:var(--ink);min-width:0}
input[type=checkbox] {width:1rem;height:1rem;vertical-align:middle} button {border:1px solid var(--accent);padding:.55rem .85rem;background:var(--accent);color:#fff;cursor:pointer}
button.secondary {background:white;color:var(--accent)} button:disabled {opacity:.45;cursor:not-allowed} :focus-visible {outline:3px solid #cb7a00;outline-offset:3px}
.toolbar {display:flex;justify-content:space-between;align-items:center;gap:.8rem;flex-wrap:wrap;margin:0 0 1rem}.actions {display:flex;gap:.5rem;flex-wrap:wrap}
.small,.meta {color:var(--muted);font-size:.85rem}.notice {border-left:4px solid #b98724;background:#fff8e9;padding:.8rem;margin:1rem 0}
.card {margin-bottom:1rem} summary {cursor:pointer;font-weight:700} summary::marker {color:var(--accent)} .title {font-size:1.15rem}
.badges {display:flex;flex-wrap:wrap;gap:.4rem;margin:.8rem 0 .2rem}.badge {background:#eaf1f2;border-radius:5px;padding:.15rem .5rem;font-size:.76rem;font-weight:650}
.badge.synthetic {background:#fff0cf}.badge.review {background:#e4f1ed} .detail {border-top:1px solid var(--line);margin-top:1rem;padding-top:.7rem}
dl {display:grid;grid-template-columns:minmax(100px,1fr) 3fr;gap:.35rem 1rem} dt {font-weight:650} dd {margin:0} p,dd,li,code {overflow-wrap:anywhere}
ul {padding-left:1.3rem}.source {border-left:3px solid #c3d9d5;padding-left:1rem;margin:1.2rem 0} code {font-size:.85rem}
#error {background:#ffeded;color:#752b26;border:1px solid #d99d98;padding:.8rem;border-radius:6px;margin-bottom:1rem}
#empty {text-align:center;padding:2rem} .pagination {display:flex;justify-content:center;gap:1rem;align-items:center;margin:1rem 0}
.facet-grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;font-size:.85rem}.facet-grid h3 {font-size:.9rem} .facet-grid ul {list-style:none;padding:0}
footer {max-width:1200px;margin:auto;padding:1rem 1.5rem 2rem;color:var(--muted);font-size:.85rem}[hidden] {display:none!important}
@media(max-width:800px) {main {grid-template-columns:1fr;padding:1rem}.filters .filter-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 .8rem}dl {grid-template-columns:1fr}dd {margin-bottom:.5rem}}
@media(max-width:420px) {.filters .filter-grid {grid-template-columns:1fr}.actions button {width:100%}}
@media print {body {background:white;font-size:11pt}header {background:white;color:black;padding:0}header p {color:black}main {display:block;padding:0}.filters,.actions,.pagination,#facet-panel {display:none}details {break-inside:avoid}.card {border:1px solid #aaa}summary {list-style:none}footer {padding:0}.notice {background:white}}
""".strip()

SCRIPT = r"""
"use strict";
(() => {
  const byId = id => document.getElementById(id);
  const error = byId("error"), list = byId("records"), empty = byId("empty");
  const exportButton = byId("export-json");
  let payload, selected = [], page = 0, valid = true;
  const fields = ["jurisdiction", "topic", "policy_stage", "verification_status", "record_type"];
  const dateFields = ["last_verified_at", "adopted_at", "announced_at", "effective_at", "target_at"];
  const names = {policy_stage:"Policy stage",verification_status:"Review status",record_type:"Record type",
    last_verified_at:"Last review",announced_at:"Announcement",adopted_at:"Adoption",effective_at:"Entry into force",target_at:"Target"};
  const label = value => names[value] || value.replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
  const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const node = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  };
  function allStrings(value) {
    if (typeof value === "string") return [value];
    if (value && typeof value === "object") return Object.values(value).flatMap(allStrings);
    return [];
  }
  function day(value) {
    if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value) || value.startsWith("0000")) return null;
    const time = Date.parse(value + "T00:00:00Z");
    return Number.isFinite(time) && new Date(time).toISOString().slice(0,10) === value ? time / 86400000 : null;
  }
  const dateValue = (record, field) => field === "last_verified_at" ? record[field] : record.dates[field];
  function paragraph(parent, heading, value) {
    parent.append(node("h3", heading), node("p", value === null ? "Unknown" : value));
  }
  function card(record) {
    const item = node("details", undefined, "card"), summary = node("summary");
    summary.append(node("span", record.title, "title"));
    const badges = node("div", undefined, "badges");
    badges.append(node("span", label(record.record_type), "badge " + record.record_type),
      node("span", "Stage: " + label(record.policy_stage), "badge"),
      node("span", "Review: " + label(record.verification_status), "badge review"));
    summary.append(badges, node("span", record.jurisdiction + " · " + label(record.topic) + " · " + record.id, "meta"));
    item.append(summary);
    const detail = node("div", undefined, "detail");
    paragraph(detail, "Precise claim", record.claim);
    paragraph(detail, "Scope", record.scope);
    paragraph(detail, "Evidence review note", record.verification_note);
    detail.append(node("h3", "Dates"));
    const dates = node("dl");
    dateFields.forEach(field => dates.append(node("dt", label(field)), node("dd", dateValue(record, field) || "Unknown")));
    detail.append(dates, node("h3", "Evidence sources"));
    record.sources.forEach((source, index) => {
      const section = node("section", undefined, "source");
      section.append(node("h3", String(index + 1) + ". " + source.title), node("p", source.publisher), node("code", source.url));
      paragraph(section, "Evidence locator", source.locator);
      paragraph(section, "What it supports", source.supports);
      section.append(node("p", "Published: " + (source.published_at || "Unknown") + " · Accessed: " + (source.accessed_at || "Unknown"), "small"));
      detail.append(section);
    });
    detail.append(node("h3", "Evidence limitations"));
    const limits = node("ul");
    record.limitations.forEach(text => limits.append(node("li", text)));
    detail.append(limits, node("h3", "Change history"));
    const history = node("ul");
    record.change_history.forEach(entry => history.append(node("li", entry.date + ": " + entry.summary)));
    detail.append(history); item.append(detail); return item;
  }
  function facets(records) {
    const grid = byId("facets"); grid.replaceChildren();
    fields.forEach(field => {
      const section = node("section"); section.append(node("h3", label(field)));
      const counts = new Map(); records.forEach(r => counts.set(r[field], (counts.get(r[field]) || 0) + 1));
      const values = node("ul");
      [...counts.keys()].sort((a,b) => compare(a.toLowerCase(),b.toLowerCase()) || compare(a,b)).forEach(value => values.append(node("li", label(value) + ": " + counts.get(value))));
      if (!counts.size) values.append(node("li", "No matches"));
      section.append(values); grid.append(section);
    });
  }
  function render() {
    const size = Number(byId("page-size").value), pages = Math.max(1, Math.ceil(selected.length / size));
    page = Math.min(page, pages - 1);
    list.replaceChildren(...selected.slice(page * size, (page + 1) * size).map(card));
    empty.hidden = selected.length > 0 || !valid;
    byId("counts").textContent = valid ? selected.length + " matched / " + payload.records.length + " total catalog records" : "Adjust filters to view results.";
    byId("page-status").textContent = "Page " + (page + 1) + " of " + pages;
    byId("previous").disabled = page === 0 || !valid;
    byId("next").disabled = page + 1 >= pages || !valid;
    exportButton.disabled = !selected.length || !valid;
    byId("print-page").disabled = !selected.length || !valid;
    facets(selected);
  }
  function refresh() {
    page = 0; valid = true; error.hidden = true;
    const from = byId("date-from").value, to = byId("date-to").value, age = byId("max-review-age").value;
    const field = byId("date-field").value, presence = byId("date-presence").value;
    const search = byId("search").value.toLowerCase();
    let message = "";
    if (!byId("date-from").checkValidity() || !byId("date-to").checkValidity() || from && day(from) === null || to && day(to) === null) message = "Use valid calendar dates in YYYY-MM-DD format.";
    else if (from && to && from > to) message = "The start date must not follow the end date.";
    else if (presence === "unknown" && (from || to)) message = "Unknown dates cannot be combined with a date range.";
    else if (!byId("max-review-age").checkValidity() || age && (!/^[0-9]{1,7}$/.test(age) || Number(age) > 3652058)) message = "Review age must be a nonnegative whole number of days within the supported range.";
    else if (Array.from(search).length > 1000) message = "Search text must contain at most 1000 characters.";
    if (message) {
      valid = false; selected = []; render(); empty.hidden = true;
      error.textContent = message; error.hidden = false; byId("counts").textContent = "Adjust filters to view results."; return;
    }
    selected = payload.records.filter(record => {
      if (fields.some(f => byId(f).value && record[f].toLowerCase() !== byId(f).value.toLowerCase())) return false;
      if (!allStrings(record).join("\n").toLowerCase().includes(search)) return false;
      const date = dateValue(record, field);
      if (presence === "known" && date === null || presence === "unknown" && date !== null) return false;
      if ((from || to) && (date === null || from && date < from || to && date > to)) return false;
      if (age !== "" && (record.last_verified_at === null || day(payload.as_of) - day(record.last_verified_at) > Number(age))) return false;
      return true;
    });
    const sort = byId("sort").value, direction = byId("descending").checked ? -1 : 1;
    const value = record => dateFields.includes(sort) ? dateValue(record, sort) : record[sort];
    selected.sort((a,b) => {
      const av = value(a), bv = value(b);
      if (av === null || bv === null) return av === bv ? compare(a.id,b.id) : av === null ? 1 : -1;
      return direction * compare(av.toLowerCase(),bv.toLowerCase()) || compare(a.id,b.id);
    });
    render();
  }
  try {
    payload = JSON.parse(byId("catalog-data").textContent);
    fields.forEach(field => {
      [...new Set(payload.records.map(record => record[field]))].sort((a,b) => compare(a.toLowerCase(),b.toLowerCase()) || compare(a,b)).forEach(value => {
        const option = node("option", label(value)); option.value = value; byId(field).append(option);
      });
    });
    byId("filters").addEventListener("input", refresh);
    byId("reset").addEventListener("click", () => {
      byId("filters").querySelectorAll("input").forEach(input => {if (input.type === "checkbox") input.checked = false; else input.value = "";});
      fields.forEach(field => byId(field).value = "");
      byId("date-field").value = "last_verified_at"; byId("date-presence").value = "any";
      byId("sort").value = "title"; byId("page-size").value = "25"; refresh(); byId("search").focus();
    });
    byId("page-size").addEventListener("change", () => {page = 0; render();});
    byId("previous").addEventListener("click", () => {if (page > 0) {page--; render();}});
    byId("next").addEventListener("click", () => {page++; render();});
    byId("print-page").addEventListener("click", () => {list.querySelectorAll("details").forEach(item => item.open = true); window.print();});
    exportButton.addEventListener("click", () => {
      if (!valid || !selected.length) return;
      const blob = new Blob([JSON.stringify({schema_version:1,records:selected}, null, 2) + "\n"], {type:"application/json"});
      const url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = "catalog-filtered.json"; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    refresh();
  } catch (_) {
    valid = false; selected = []; list.replaceChildren(); empty.hidden = true;
    error.textContent = "The catalog could not be displayed. Regenerate it from valid local records."; error.hidden = false;
    byId("counts").textContent = "Catalog unavailable."; exportButton.disabled = true;
  }
})();
""".strip()


def digest(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def render_html(catalog: Catalog) -> str:
    payload = json.dumps({"as_of": catalog.as_of.isoformat(), "records": catalog.records}, ensure_ascii=True, allow_nan=False)
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    csp = ("default-src 'none'; script-src 'sha256-" + digest(SCRIPT) + "'; style-src 'sha256-" + digest(CSS) +
           "'; connect-src 'none'; img-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'")
    def options(values, selected):
        return "".join('<option value="' + html.escape(value, quote=True) + '"' + (" selected" if value == selected else "") + ">" + html.escape(value.replace("_", " ").capitalize()) + "</option>" for value in values)
    categories = "".join('<div><label for="' + field + '">' + {"policy_stage": "Policy stage", "verification_status": "Review status", "record_type": "Record type"}.get(field, field.capitalize()) + '</label><select id="' + field + '"><option value="">All</option></select></div>' for field in FACET_FIELDS)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{html.escape(csp, quote=True)}">
<title>Offline Policy Catalog | Open Europe Preparedness</title><style>{CSS}</style></head>
<body><header><div class="kicker">Open Europe Preparedness · Offline explorer</div><h1>Explore the evidence.<br>Keep the distinctions.</h1>
<p>Search policy records, inspect what their sources support, and retain the limits of each claim.</p>
<p class="cutoff">Validation and review-age cutoff: {catalog.as_of.isoformat()}</p></header>
<main><section class="panel filters" aria-labelledby="filter-title"><h2 id="filter-title">Find records</h2>
<div id="filters"><label for="search">Search all record text</label><input id="search" type="search" maxlength="1000" placeholder="Claim, source or limitation" autocomplete="off">
<div class="filter-grid">{categories}
<div><label for="date-field">Date field</label><select id="date-field">{options(DATE_FIELDS, 'last_verified_at')}</select></div>
<div><label for="date-presence">Date availability</label><select id="date-presence"><option value="any">Any</option><option value="known">Known dates</option><option value="unknown">Unknown dates only</option></select></div>
<div><label for="date-from">From (inclusive)</label><input type="date" id="date-from" min="0001-01-01" max="9999-12-31"></div>
<div><label for="date-to">To (inclusive)</label><input type="date" id="date-to" min="0001-01-01" max="9999-12-31"></div>
<div><label for="max-review-age">Maximum review age (days)</label><input id="max-review-age" type="number" min="0" max="3652058" step="1" placeholder="Any known or unknown review"></div>
<div><label for="sort">Sort records by</label><select id="sort">{options(SORT_FIELDS, 'title')}</select></div></div>
<label><input type="checkbox" id="descending"> Descending order</label></div>
<p class="small">Date ranges and age limits exclude unknown dates. Age is measured at the fixed cutoff, not the browser clock.</p><button type="button" class="secondary" id="reset">Reset filters</button></section>
<section aria-label="Catalog results"><div class="toolbar"><div><h2>Policy catalog</h2><div id="counts" role="status" aria-live="polite">Loading local records...</div></div>
<div class="actions"><button id="export-json" type="button" disabled>Download filtered JSON</button><button id="print-page" type="button" class="secondary" disabled>Print this page</button></div></div>
<div class="notice">{html.escape(NOTICE)} The cutoff does not reconstruct historical policy truth. Source URLs are displayed as text; this page makes no network requests.</div>
<div id="error" role="alert" hidden></div><noscript><p class="notice">Enable JavaScript locally to use filters and evidence details, or use the Python query command.</p></noscript>
<div id="empty" class="panel" hidden><h2>No matching records</h2><p>Remove a filter or use Reset filters to see the full catalog.</p></div><div id="records"></div>
<div class="pagination"><button id="previous" class="secondary" type="button" disabled>Previous</button><span id="page-status" aria-live="polite"></span><button id="next" class="secondary" type="button" disabled>Next</button></div>
<label for="page-size">Records per page</label><select id="page-size"><option>10</option><option selected>25</option><option>50</option><option>100</option></select>
<details id="facet-panel" class="panel"><summary>Counts across all matching records</summary><p class="small">Counts include every match before pagination and distinguish synthetic examples from real records.</p><div id="facets" class="facet-grid"></div></details>
</section></main><footer>Generated from validated local inputs. Expand a record for evidence, dates, limitations and change history. Download includes every filtered record with full original provenance; review its contents before sharing. No storage, telemetry or external resources are used.</footer>
<script type="application/json" id="catalog-data">{payload}</script><script>{SCRIPT}</script></body></html>
'''


def write_html(catalog: Catalog, output: str | Path) -> None:
    """Atomically create a 0600 POSIX file without replacing files or following links."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise CatalogError("Safe HTML output requires a POSIX filesystem.")
    content = render_html(catalog).encode("utf-8")
    path = Path(output).absolute()
    if ".." in path.parts or path.name in ("", ".", ".."):
        raise CatalogError("The output location is not supported.")
    directory_fd = None
    temporary = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory_fd = os.open(path.anchor, flags)
        for part in path.parts[1:-1]:
            try:
                child_fd = os.open(part, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                os.mkdir(part, 0o700, dir_fd=directory_fd)
                child_fd = os.open(part, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        candidate = ".catalog-" + secrets.token_hex(12) + ".tmp"
        fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        temporary = candidate
        with os.fdopen(fd, "wb") as target:
            os.fchmod(target.fileno(), 0o600)
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
    except (OSError, ValueError):
        raise CatalogError("Unable to create HTML output. Choose a new file in a directory without symbolic links.") from None
    finally:
        if directory_fd is not None:
            try:
                if temporary is not None:
                    os.unlink(temporary, dir_fd=directory_fd)
            except OSError:
                raise CatalogError("Unable to finish HTML output cleanup.") from None
            finally:
                os.close(directory_fd)
