"""Self-contained, text-only maintenance report with fixed hashed assets."""
import html
import json

from .catalog_html import CSS as BASE_CSS, digest
from .maintenance import SELECTION_LIMITATIONS, verify_report

CSS = BASE_CSS + r"""
header {background:#233951}.comparison-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}
.evidence {border:1px solid var(--line);border-radius:8px;padding:1rem;min-width:0}.field-change {padding:.7rem 0;border-bottom:1px solid var(--line)}
.field-change p {margin:.25rem 0}.badge.added {background:#def0e2}.badge.removed {background:#f8e3dc}.badge.changed {background:#fff1c6}
.view-buttons {display:flex;gap:.5rem;margin-bottom:1rem}.view-buttons button[aria-pressed=true] {background:#233951;border-color:#233951}
.hash {font-size:.7rem;display:block;overflow-wrap:anywhere}.reason {padding:.5rem;background:#fff8e9;border-radius:6px;margin:.4rem 0}
#snapshot-context {margin-bottom:1rem}.metadata {margin:0}.panel summary {font-size:.95rem}.section-space {margin-top:1rem}
@media(max-width:1000px) {.comparison-grid {grid-template-columns:1fr}}
@media print {.view-buttons,#snapshot-context button {display:none}.comparison-grid {display:block}.evidence {margin-bottom:1rem}.card {break-inside:auto}}
"""

SCRIPT = r"""
"use strict";
(() => {
  const el = id => document.getElementById(id);
  const node = (tag,text,className) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
  const compare = (a,b) => a < b ? -1 : a > b ? 1 : 0;
  const label = value => value.replaceAll("_"," ").replace(/^./,c=>c.toUpperCase());
  let report, before, after, rows=[], filtered=[], view="all", page=0;
  function textSection(parent,heading,value) {parent.append(node("h3",heading),node("p",value===null?"Unknown":value));}
  function evidence(record,title) {
    const box=node("section",undefined,"evidence");box.append(node("h3",title));
    if(!record){box.append(node("p","Absent from this snapshot. This does not establish adoption or repeal."));return box;}
    box.append(node("p",record.title),node("code",record.id));
    const meta=node("dl");
    [["Record type",record.record_type],["Jurisdiction",record.jurisdiction],["Topic",record.topic],["Policy stage",record.policy_stage],["Review status",record.verification_status],["Last review",record.last_verified_at],...Object.entries(record.dates)].forEach(([key,value])=>meta.append(node("dt",label(key)),node("dd",value===null?"Unknown":value)));
    box.append(meta);textSection(box,"Precise claim",record.claim);textSection(box,"Scope",record.scope);textSection(box,"Review note",record.verification_note);
    box.append(node("h3","Evidence sources"));
    record.sources.forEach((source,index)=>{
      const sourceBox=node("div",undefined,"source");sourceBox.append(node("h3",String(index+1)+". "+source.title),node("p",source.publisher),node("code",source.url));
      textSection(sourceBox,"Locator",source.locator);textSection(sourceBox,"Supports",source.supports);
      sourceBox.append(node("p","Published: "+(source.published_at||"Unknown")+" · Accessed: "+(source.accessed_at||"Unknown"),"small"));box.append(sourceBox);
    });
    box.append(node("h3","Evidence limitations"));const limits=node("ul");record.limitations.forEach(value=>limits.append(node("li",value)));box.append(limits,node("h3","Change history"));
    const history=node("ul");record.change_history.forEach(entry=>history.append(node("li",entry.date+": "+entry.summary)));box.append(history);return box;
  }
  function reasonText(reason) {return label(reason.code)+" · "+reason.path+(reason.age_days===null?"":" · "+reason.age_days+" days old; limit "+reason.limit_days);}
  function card(row) {
    const detail=node("details",undefined,"card"),summary=node("summary"),record=row.after||row.before;
    summary.append(node("span",record.title,"title"));const badges=node("div",undefined,"badges");
    badges.append(node("span",label(row.change),"badge "+row.change),node("span",label(record.record_type),"badge "+record.record_type));
    if(row.policy_stage_changed)badges.append(node("span","Policy stage changed","badge changed"));
    if(row.verification_status_changed)badges.append(node("span","Review status changed","badge changed"));
    badges.append(node("span",row.reasons.length+" triage reasons","badge"));summary.append(badges,node("span",row.id+" · "+record.jurisdiction,"meta"));detail.append(summary);
    const body=node("div",undefined,"detail");body.append(node("h3","Structural triage"));
    if(!row.after)body.append(node("p","Absent from the after snapshot; this record is outside its review queue."));
    else if(!row.reasons.length)body.append(node("p","No configured triage reason. This is not evidence of truth, freshness beyond these limits, or human certification."));
    row.reasons.forEach(reason=>body.append(node("p",reasonText(reason),"reason")));
    if(report.artifact_type==="catalog_comparison") {
      body.append(node("h3","Field-level changes"));
      if(!row.field_changes.length)body.append(node("p","No stored record fields changed."));
      row.field_changes.forEach(change=>{
        const box=node("div",undefined,"field-change");box.append(node("code",change.path||"/"));
        box.append(node("p","Before: "+(change.before_present?JSON.stringify(change.before):"Absent")),node("p","After: "+(change.after_present?JSON.stringify(change.after):"Absent")));body.append(box);
      });
    }
    const pair=node("div",undefined,"comparison-grid");
    if(before)pair.append(evidence(row.before,"Before snapshot"));
    pair.append(evidence(row.after,before?"After snapshot":"Current snapshot"));body.append(pair);detail.append(body);return detail;
  }
  function refresh() {
    page=0;const search=el("search").value.toLowerCase();
    filtered=rows.filter(row=>{
      const record=row.after||row.before;
      if(view==="queue"&&!row.reasons.length)return false;
      if(el("change-filter").value&&row.change!==el("change-filter").value)return false;
      if(el("source-count-filter").value&&(el("source-count-filter").value==="single")!==(record.sources.length===1))return false;
      if(el("publisher-filter").value&&!record.sources.some(source=>source.publisher===el("publisher-filter").value))return false;
      if(el("review-date-filter").value&&(el("review-date-filter").value==="known")!==(record.last_verified_at!==null))return false;
      if(el("stage-filter").value&&record.policy_stage!==el("stage-filter").value)return false;
      if(el("topic-filter").value&&record.topic!==el("topic-filter").value)return false;
      if(el("jurisdiction").value&&record.jurisdiction!==el("jurisdiction").value)return false;
      if(el("record-type").value&&record.record_type!==el("record-type").value)return false;
      if(el("status-filter").value&&record.verification_status!==el("status-filter").value)return false;
      if(el("reason-filter").value&&!row.reasons.some(r=>r.code===el("reason-filter").value))return false;
      const transition=el("transition-filter").value;
      if(transition&&!row[transition])return false;
      return JSON.stringify(row).toLowerCase().includes(search);
    });
    const sort=el("sort").value;
    filtered.sort((a,b)=>sort==="reasons"?b.reasons.length-a.reasons.length||compare(a.id,b.id):compare((sort==="title"?(a.after||a.before).title:a[sort]).toLowerCase(),(sort==="title"?(b.after||b.before).title:b[sort]).toLowerCase())||compare(a.id,b.id));
    render();
  }
  function render() {
    const size=Number(el("page-size").value),pages=Math.max(1,Math.ceil(filtered.length/size));page=Math.min(page,pages-1);
    el("records").replaceChildren(...filtered.slice(page*size,(page+1)*size).map(card));el("empty").hidden=filtered.length>0;
    el("counts").textContent=filtered.length+" matched / "+rows.length+" snapshot record IDs · "+report.review_queue.queued_count+" records in the full after/current review queue";
    const states=report.artifact_type==="catalog_comparison"?["added","removed","changed","unchanged"]:["current"];
    el("change-counts").textContent="Across all matches: "+states.map(state=>label(state)+" "+filtered.filter(row=>row.change===state).length).join(" · ");
    el("page-status").textContent="Page "+(page+1)+" of "+pages;el("previous").disabled=page===0;el("next").disabled=page+1>=pages;
    el("download-selection").disabled=!filtered.length;el("print-page").disabled=!filtered.length;
    el("expand-visible").disabled=!filtered.length;el("collapse-visible").disabled=!filtered.length;
    const counts=new Map();filtered.forEach(row=>row.reasons.forEach(reason=>counts.set(reason.code,(counts.get(reason.code)||0)+1)));
    const target=el("reason-counts");target.replaceChildren();[...counts.keys()].sort().forEach(code=>target.append(node("li",label(code)+": "+counts.get(code))));
    if(!counts.size)target.append(node("li","No configured reasons among these matches."));
  }
  function download(value,name) {
    const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)+"\n"],{type:"application/json"}));
    const link=document.createElement("a");link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function options(id,values,display=label) {for(const value of [...new Set(values)].sort()){const option=node("option",display(value));option.value=value;el(id).append(option);}}
  try {
    const payload=JSON.parse(el("maintenance-data").textContent);report=payload.report;
    before=report.before_snapshot||null;after=report.after_snapshot||report.snapshot;
    const old=new Map((before?before.dataset.records:[]).map(r=>[r.id,r])),current=new Map(after.dataset.records.map(r=>[r.id,r]));
    const queue=new Map(report.review_queue.entries.map(entry=>[entry.id,entry.reasons]));
    rows=(report.changes||after.dataset.records.map(r=>({id:r.id,change:"current",field_changes:[],policy_stage_changed:false,verification_status_changed:false}))).map(change=>({...change,before:old.get(change.id)||null,after:current.get(change.id)||null,reasons:queue.get(change.id)||[]}));
    rows.forEach(row=>row.limitations_changed=row.change==="changed"&&row.field_changes.some(change=>change.path==="/limitations"||change.path.startsWith("/limitations/")));
    rows.forEach(row=>row.source_evidence_changed=row.change==="changed"&&row.field_changes.some(change=>change.path==="/sources"||change.path.startsWith("/sources/")));
    rows.forEach(row=>row.policy_dates_changed=row.change==="changed"&&row.field_changes.some(change=>change.path==="/dates"||change.path.startsWith("/dates/")));
    options("change-filter",rows.map(r=>r.change));options("jurisdiction",rows.map(r=>(r.after||r.before).jurisdiction));options("record-type",rows.map(r=>(r.after||r.before).record_type));
    options("publisher-filter",rows.flatMap(r=>(r.after||r.before).sources.map(source=>source.publisher)),value=>value);
    options("stage-filter",rows.map(r=>(r.after||r.before).policy_stage));
    options("topic-filter",rows.map(r=>(r.after||r.before).topic));
    options("status-filter",rows.map(r=>(r.after||r.before).verification_status));options("reason-filter",Object.keys(report.review_queue.reason_counts));
    el("context").textContent="Review cutoff: "+report.review_queue.as_of+" · Maximum review age: "+report.review_queue.max_review_age+" days · Maximum source-access age: "+report.review_queue.max_source_age+" days";
    el("after-hash").textContent="After/current snapshot: "+after.snapshot_sha256;
    if(before){el("before-hash").textContent="Before snapshot: "+before.snapshot_sha256;report.snapshot_metadata_changes.forEach(change=>el("metadata-changes").append(node("li",label(change.field)+": "+String(change.before)+" → "+String(change.after))));}
    else {el("download-before").hidden=true;el("transition-controls").hidden=true;el("change-controls").hidden=true;}
    el("report-hash").textContent="Report: "+report.report_sha256;
    el("filters").addEventListener("input",refresh);
    for(const mode of ["all","queue"])el("view-"+mode).addEventListener("click",()=>{view=mode;for(const name of ["all","queue"])el("view-"+name).setAttribute("aria-pressed",String(name===mode));refresh();});
    el("reset").addEventListener("click",()=>{el("filters").querySelectorAll("select").forEach(control=>control.value="");el("search").value="";el("sort").value="id";view="all";el("view-all").setAttribute("aria-pressed","true");el("view-queue").setAttribute("aria-pressed","false");refresh();el("search").focus();});
    el("sort").addEventListener("change",refresh);el("page-size").addEventListener("change",()=>{page=0;render();});
    el("previous").addEventListener("click",()=>{if(page>0){page--;render();}});el("next").addEventListener("click",()=>{page++;render();});
    el("download-report").addEventListener("click",()=>download(report,"maintenance-report.json"));
    el("download-before").addEventListener("click",()=>{if(before)download(before,"catalog-before-snapshot.json");});
    el("download-after").addEventListener("click",()=>download(after,"catalog-after-snapshot.json"));
    el("download-selection").addEventListener("click",()=>{if(filtered.length)download({schema_version:1,artifact_type:"maintenance_selection",source_report_sha256:report.report_sha256,entries:filtered.map(row=>({id:row.id,change:row.change,field_changes:row.field_changes,before:row.before,after:row.after,review_reasons:row.reasons})),limitations:payload.selection_limitations},"maintenance-selection.json");});
    for(const [id,open] of [["expand-visible",true],["collapse-visible",false]])el(id).addEventListener("click",()=>el("records").querySelectorAll("details.card").forEach(item=>item.open=open));
    el("print-page").addEventListener("click",()=>{el("records").querySelectorAll("details").forEach(item=>item.open=true);window.print();});
    refresh();
  } catch (_) {
    el("error").hidden=false;el("error").textContent="The maintenance report could not be displayed. Regenerate it from verified local artifacts.";
    el("records").replaceChildren();el("counts").textContent="Report unavailable.";
    document.querySelectorAll("button").forEach(button=>button.disabled=true);
  }
})();
""".strip()


def render_report(report: dict) -> str:
    checked = verify_report(report)
    payload = json.dumps({"report": checked, "selection_limitations": SELECTION_LIMITATIONS}, ensure_ascii=True, allow_nan=False)
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    csp = "default-src 'none'; script-src 'sha256-" + digest(SCRIPT) + "'; style-src 'sha256-" + digest(CSS) + "'; connect-src 'none'; img-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{html.escape(csp, quote=True)}"><title>Offline Maintenance Review | Open Europe Preparedness</title><style>{CSS}</style></head>
<body><header><div class="kicker">Open Europe Preparedness · Offline maintenance</div><h1>Review what changed.<br>Keep the evidence intact.</h1><p>Compare complete catalog snapshots and prepare human-reviewed corrections using explicit structural triage reasons.</p><p id="context" class="cutoff"></p></header>
<main><section class="panel filters" aria-label="Maintenance filters"><h2>Focus the review</h2><div id="filters"><label for="search">Search records, evidence and changes</label><input id="search" type="search" maxlength="1000" autocomplete="off" placeholder="Claim, source, field or reason">
<div class="filter-grid">
<div><label for="source-count-filter">Source entries</label><select id="source-count-filter"><option value="">Any source count</option><option value="single">One source entry</option><option value="multiple">Multiple source entries</option></select></div>
<div><label for="publisher-filter">Source publisher</label><select id="publisher-filter"><option value="">All publishers</option></select></div>
<div><label for="review-date-filter">Review date</label><select id="review-date-filter"><option value="">Known or missing</option><option value="known">Known review date</option><option value="missing">Missing review date</option></select></div>
<div><label for="stage-filter">Policy stage</label><select id="stage-filter"><option value="">All stages</option></select></div>
<div><label for="topic-filter">Topic</label><select id="topic-filter"><option value="">All topics</option></select></div>
<div id="change-controls"><label for="change-filter">Snapshot change</label><select id="change-filter"><option value="">All changes</option></select></div><div><label for="jurisdiction">Jurisdiction</label><select id="jurisdiction"><option value="">All</option></select></div><div><label for="record-type">Record type</label><select id="record-type"><option value="">All</option></select></div><div><label for="status-filter">Record review status</label><select id="status-filter"><option value="">All</option></select></div><div><label for="reason-filter">Structural triage reason</label><select id="reason-filter"><option value="">All reasons</option></select></div><div id="transition-controls"><label for="transition-filter">Independent field transitions</label><select id="transition-filter"><option value="">All</option><option value="limitations_changed">Evidence limitations changed</option><option value="source_evidence_changed">Source evidence changed</option><option value="policy_dates_changed">Policy dates changed</option><option value="policy_stage_changed">Policy stage changed</option><option value="verification_status_changed">Review status changed</option></select></div></div></div>
<label for="sort">Order records</label><select id="sort"><option value="id">Record ID</option><option value="title">Title</option><option value="change">Snapshot change</option><option value="reasons">Most triage reasons</option></select><p class="small">Filters use the after/current record, or the before record when absent after. Reason counts are overlapping flags, not severity scores.</p><button id="reset" class="secondary" type="button">Reset filters</button></section>
<section aria-label="Maintenance results"><div class="toolbar"><h2>Maintenance review</h2><div class="actions"><button id="download-report" type="button">Download full review JSON</button><button id="download-selection" type="button" class="secondary" disabled>Download filtered review packet</button><button id="expand-visible" type="button" class="secondary" disabled>Expand visible evidence</button><button id="collapse-visible" type="button" class="secondary" disabled>Collapse visible evidence</button><button id="print-page" type="button" class="secondary" disabled>Print this page</button></div></div>
<div class="notice">This is structural triage, not a factual update or human certification. Removed means absent from the supplied after snapshot, never repealed. Policy stage and review status remain independent. Complete inputs remain embedded even when hidden by filters.</div>
<details id="snapshot-context" class="panel"><summary>Snapshot identities and validation context</summary><p class="small">Hashes identify consistency, not authenticity. Cutoffs describe validation context, not historical policy truth. This HTML was checked when generated; it can subsequently be edited.</p><code id="before-hash" class="hash"></code><code id="after-hash" class="hash"></code><code id="report-hash" class="hash"></code><ul id="metadata-changes" class="metadata"></ul><div class="actions"><button id="download-before" type="button" class="secondary">Download before snapshot</button><button id="download-after" type="button" class="secondary">Download after/current snapshot</button></div></details>
<div class="view-buttons"><button id="view-all" type="button" aria-pressed="true">All snapshot records</button><button id="view-queue" type="button" aria-pressed="false">Review queue only</button></div><p id="counts" role="status" aria-live="polite">Loading local report...</p><p id="change-counts" class="small"></p><div id="error" role="alert" hidden></div><noscript><p class="notice">Enable JavaScript locally to explore this report, or inspect its JSON with the maintenance CLI.</p></noscript>
<div id="empty" class="panel" hidden><h2>No matching records</h2><p>Remove a filter or reset the view. An empty queue does not certify policy truth.</p></div><div id="records"></div><div class="pagination"><button id="previous" class="secondary" type="button" disabled>Previous</button><span id="page-status" aria-live="polite"></span><button id="next" class="secondary" type="button" disabled>Next</button></div><label for="page-size">Records per page</label><select id="page-size"><option>10</option><option selected>25</option><option>50</option></select><details class="panel section-space"><summary>Reasons across all filtered matches</summary><ul id="reason-counts"></ul></details></section></main>
<footer>Source URLs are literal text. No network requests, external resources, browser storage or telemetry are used. Full JSON and snapshot downloads retain complete artifacts; filtered packets include selected before/after evidence across all pages and are not full snapshots. Review all content before sharing.</footer><script id="maintenance-data" type="application/json">{payload}</script><script>{SCRIPT}</script></body></html>'''
