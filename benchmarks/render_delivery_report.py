"""Deterministic offline delivery receipt report, from recorded results only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmarks.render_report import CSS

ROOT = Path(__file__).resolve().parents[1]


def compact(value):
    """Keep every returned context; omit repeated candidate/prose diagnostics."""
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items()
                if key not in {'candidate_projection', 'explanation'}}
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def collect(directory):
    path = directory / 'results.json'
    if not path.exists():
        return {'status': 'pending'}
    result = json.loads(path.read_text())
    if result.get('status') != 'complete':
        return {'status': 'pending', 'recorded_status': result.get('status')}
    result = compact(result)
    result['limitations'] = [line.replace('observer', 'recipient').replace('Observer', 'Recipient').replace(' or quantum', '').replace(' or consciousness', '') for line in result.get('limitations', [])]
    return {**result, 'results_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


EXTRA_CSS = '''
.delivery-controls{display:grid;grid-template-columns:2fr 1fr 1fr;gap:14px;margin:22px 0}.delivery-controls label{display:block;font-size:13px;line-height:1.8;color:#afc1d0}.delivery-controls select{width:100%;padding:11px;border:1px solid #49606d;border-radius:6px;color:#e2ecf3;background:#13222d;font:inherit}.coordinates{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0}.coordinates div{background:#15232d;border:1px solid #354854;border-radius:6px;padding:12px;overflow-wrap:anywhere}.coordinates span{display:block;color:#91a6b7;font-size:12px;margin-bottom:7px}.coordinates code{font-size:12px}.compare{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.method-column{min-width:0;background:#111f29;border:1px solid #344958;border-radius:8px;padding:20px}.method-column h3{font-size:17px}.method-stats{color:#aac1cd;font-size:13px;line-height:1.8;margin:12px 0}.claim{margin:16px 0;padding:15px;border:1px solid #43596a;border-radius:6px;background:#172630;overflow-wrap:anywhere}.claim h4{font-size:14px;margin:0 0 8px}.claim p{font-size:13px;line-height:1.7}.item-id{font-family:monospace;font-size:11px;color:#afc5d0}.passage{padding:10px;margin:10px 0;border-left:3px solid #729eb6;background:#1a303e}.event{font-size:12px;padding:9px;background:#27303a;margin:7px 0}.hidden-leak{border-color:#e99989;background:#3c292a}.leak-tag{display:inline-block;color:#ffb8a9;font-size:11px;font-weight:700;margin:0 8px 6px 0}.missing{color:#ead19e;background:#332e24;border:1px solid #726144;padding:12px;margin:12px 0;border-radius:5px;font-size:13px;line-height:1.7;overflow-wrap:anywhere}.leak-summary{color:#ffd0c2;background:#432b2a;border:1px solid #a86658;padding:12px;border-radius:5px;font-size:13px;line-height:1.7;overflow-wrap:anywhere}.delivery-presets{display:flex;flex-wrap:wrap;gap:9px;margin:14px 0}.delivery-presets button{border:1px solid #648398;border-radius:5px;padding:10px 13px;color:#c5ddeb;background:#1a303e;font-size:13px}.delivery-presets .red{color:#ffd0c2;border-color:#a66e67;background:#362b2d}.gold-box{padding:15px;border:1px solid #586c54;border-radius:6px;background:#202e25;color:#cdddc7;line-height:1.8;font-size:13px;overflow-wrap:anywhere}.report-links{display:flex;flex-wrap:wrap;gap:18px;line-height:1.8;font-size:13px}.small-note{font-size:13px;color:#a7bccb;line-height:1.8}.receipt-table{max-height:330px;overflow:auto}.receipt-table td{font-size:12px}button:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid #dfc88c;outline-offset:3px}@media(max-width:850px){.compare{grid-template-columns:1fr}.delivery-controls{grid-template-columns:1fr}.coordinates{grid-template-columns:1fr}.method-column{padding:15px}} 
'''


JS = r'''
const D=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=x=>Number.isFinite(x)?(100*x).toFixed(1)+'%':'—',ms=x=>Number.isFinite(x)?(1000*x).toFixed(2)+' ms':'—';
const methods=['Global temporal','Scalar clock','Filter after projection','Ordinary SQL receipt filter','Delivery projection'];
let selected='oq10',left='Global temporal',right='Delivery projection';
function raw(title,data){return `<details class="protocol-details"><summary>${esc(title)}</summary><pre>${esc(JSON.stringify(data,null,2))}</pre></details>`;}
function gold(q){return `<div class="gold-box"><strong>Manually specified gold</strong><br>Assertions: ${esc(q.gold_assertion_ids.join(', ')||'∅')}<br>Passages: ${esc(q.gold_evidence_ids.join(', ')||'∅')}<br>Lifecycle events: ${esc(q.gold_event_ids.join(', ')||'∅')}<br><strong>Rationale:</strong> ${esc(q.rationale)}</div>`;}
function claim(row,leaks){const hidden=(type,id)=>leaks.some(x=>x.type===type&&x.id===id),tag=(type,id)=>hidden(type,id)?'<span class="leak-tag">HIDDEN ITEM RETURNED</span>':'';return `<article class="claim ${hidden('assertion',row.id)?'hidden-leak':''}">${tag('assertion',row.id)}<h4>${esc(row.subject)} → ${esc(row.predicate)} → ${esc(row.object)}</h4><div class="item-id">${esc(row.id)} · ${esc(row.status)} · relevance ${esc(row.score)}</div>${(row.evidence||[]).map(p=>`<div class="passage ${hidden('evidence',p.id)?'hidden-leak':''}">${tag('evidence',p.id)}<span class="item-id">PASSAGE ${esc(p.id)}</span><p>${esc(p.text)}</p></div>`).join('')}${(row.events||[]).map(ev=>`<div class="event ${hidden('event',ev.id)?'hidden-leak':''}">${tag('event',ev.id)}<strong>${esc(ev.type)}</strong> · <span class="item-id">${esc(ev.id)}</span><br>Effective ${esc(ev.effective_at)}${ev.replacement_id?` · replacement ${esc(ev.replacement_id)}`:''}</div>`).join('')}</article>`;}
function methodColumn(label,q){const row=D.methods[label]?.per_query[q.id];if(!row)return `<section class="method-column"><h3>${esc(label)}</h3><p>No recorded result for this question.</p></section>`;return `<section class="method-column"><h3>${esc(label)}</h3><div class="method-stats">${row.results.length} returned assertions · ${row.eligible_count} eligible candidates · ${ms(row.seconds)}</div>${row.leaks.length?`<div class="leak-summary"><strong>Hidden-item leakage:</strong> ${row.leaks.map(x=>esc(x.type+': '+x.id)).join(', ')}</div>`:'<p class="small-note">No hidden returned items recorded.</p>'}${row.missing_support.length?`<div class="missing"><strong>Missing gold support:</strong> ${row.missing_support.map(esc).join(', ')}</div>`:'<p class="small-note">No missing gold support recorded.</p>'}${row.results.length?row.results.map(item=>claim(item,row.leaks)).join(''):'<p class="small-note">No assertions returned. This is not automatically a correct abstention: a separately received passage can still be required.</p>'}${raw('Exact support accounting',{gold:row.gold_support,found:row.found_support,missing:row.missing_support})}</section>`;}
function receipts(q){const ids=new Set([...q.gold_assertion_ids,...q.gold_evidence_ids,...q.gold_event_ids]);for(const method of methods)for(const a of D.methods[method]?.per_query[q.id]?.results||[]){ids.add(a.id);for(const ev of a.evidence||[])ids.add(ev.id);for(const ev of a.events||[])ids.add(ev.id);}const rows=D.fixture.receipts.filter(r=>r.recipient_id===q.recipient_id&&ids.has(r.item_id));return `<details class="protocol-details"><summary>Recorded receipts for this recipient and inspected items</summary><p class="small-note">A row can be logged after the ledger cutoff or received after delivery time. Its presence in this audit table does not mean it was visible in the selected query.</p><div class="table-wrap receipt-table"><table><thead><tr><th>Item</th><th>Received at</th><th>Recorded at</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.item_type)} · ${esc(r.item_id)}</td><td>${esc(r.received_at)}</td><td>${esc(r.recorded_at)}</td></tr>`).join('')}</tbody></table></div></details>`;}
function renderCase(){const q=D.fixture.queries.find(x=>x.id===selected)||D.fixture.queries[0];selected=q.id;$('case-query').value=selected;$('case-body').innerHTML=`<h3>${esc(q.query)}</h3><p class="small-note">${esc(q.id)} · ${esc(q.family)} · <strong>${esc(q.recipient_id)}</strong></p><div class="coordinates"><div><span>Valid time · when the claim applies</span><code>${esc(q.scope.valid_at)}</code></div><div><span>Known time · shared ledger cutoff</span><code>${esc(q.scope.known_at)}</code></div><div><span>Recipient time · receipt cutoff</span><code>${esc(q.scope.received_by)}</code></div></div><p class="small-note">World ${esc(q.scope.world)} · Plane ${esc(q.scope.plane)} · Perspective ${esc(q.scope.perspective)}</p>${gold(q)}<div class="compare" style="margin-top:20px">${methodColumn(left,q)}${methodColumn(right,q)}</div>${receipts(q)}`;}
function render(){if(D.status!=='complete'){$('content').innerHTML='<section class="panel"><h2>Experiment pending</h2><p>No completed results.json is present. No metrics or outcomes have been substituted.</p></section>';return;}
const c=D.comparison,tied=c.identical_top5_ids_and_scores===c.queries&&c.identical_candidate_projections===c.queries;
$('content').innerHTML=`<div class="cards"><div class="card"><span>Synthetic queries</span><strong>${D.fixture.queries.length}</strong><small>Fixed manually authored gold</small></div><div class="card"><span>Assertions / events / receipts</span><strong>${D.fixture.assertions.length} / ${D.fixture.events.length} / ${D.fixture.receipts.length}</strong><small>Receipt is availability, not endorsement</small></div><div class="card"><span>SQL / delivery exact top-5 ties</span><strong>${c.identical_top5_ids_and_scores} / ${c.queries}</strong><small>Candidate projection ties: ${c.identical_candidate_projections} / ${c.queries}</small></div></div><div class="notice"><strong>${tied?'Ordinary receipt filtering ties the delivery adapter.':'Inspect the SQL / delivery differences.'}</strong> ${tied?'The same receipt and temporal information is sufficient for ordinary SQL to implement this experiment’s delivery projection. This establishes ordinary SQL equivalence for this fixture; the ordering of receipt filtering before lifecycle projection remains the relevant difference.':'Equivalence was not established for all recorded queries; the raw comparison is preserved.'}</div><section class="panel"><h2>Five methods, the same ranking</h2><p class="small-note">Support includes required passages; an empty assertion-gold list does not imply an empty answer. Leakage audits assertion, passage and event receipt visibility. Latency changes with candidate size and shared-machine load.</p><div class="table-wrap"><table><thead><tr><th>Method</th><th>Leakage queries ↓</th><th>Support recall ↑</th><th>Support precision ↑</th><th>Complete support ↑</th><th>Empty abstention ↑</th><th>False abstention ↓</th><th>p50 / p95</th></tr></thead><tbody>${methods.map(label=>{const m=D.methods[label];if(!m)return '';return `<tr><td>${esc(label)}</td><td>${pct(m.metrics.leakage_query_rate)}</td><td>${pct(m.metrics.support_recall)}</td><td>${pct(m.metrics.support_precision)}</td><td>${pct(m.metrics.complete_support_rate)}</td><td>${pct(m.metrics.empty_abstention_rate)}</td><td>${pct(m.metrics.false_abstention_rate)}</td><td>${ms(m.latency.p50_seconds)} / ${ms(m.latency.p95_seconds)}</td></tr>`;}).join('')}</tbody></table></div><p class="small-note">Preparatory warm-up: ${Number.isFinite(D.preparation_seconds)?D.preparation_seconds.toFixed(2)+' s':'see raw result'}. No generated answers or LLM judge. Relevance score is not a truth probability. Lifecycle events follow a fixed scenario policy; recipient-specific agreement and trust are not modeled.</p></section><section class="panel"><h2>Inspect every recorded case</h2><p class="small-note">Red and blue are recipient names, not truth labels. The correction examples expose each recipient’s actual time coordinates; they are not silently aligned.</p><div class="delivery-presets"><button class="red" data-example="oq10">Red · before correction receipt</button><button data-example="oq14">Blue · two reports, correction unseen</button><button class="red" data-example="oq13">Red · corrected report received</button><button data-example="oq41">Independent passage · known failure</button></div><div class="delivery-controls"><label for="case-query">Recorded question<select id="case-query">${D.fixture.queries.map(q=>`<option value="${esc(q.id)}">${esc(q.id+' · '+q.recipient_id+' · '+q.query)}</option>`).join('')}</select></label><label for="left-method">Left method<select id="left-method">${methods.map(m=>`<option${m===left?' selected':''}>${esc(m)}</option>`).join('')}</select></label><label for="right-method">Right method<select id="right-method">${methods.map(m=>`<option${m===right?' selected':''}>${esc(m)}</option>`).join('')}</select></label></div><div id="case-body" aria-live="polite"></div></section><section class="panel"><h2>Limits and reproducibility</h2><ul class="caveats">${D.limitations.map(l=>`<li>${esc(l)}</li>`).join('')}</ul>${raw('Model, fixture and implementation provenance',{model:D.model,fixture_sha256:D.fixture_sha256,source_sha256:D.source_sha256,results_sha256:D.results_sha256})}${raw('Complete aggregate support accounting',Object.fromEntries(methods.filter(m=>D.methods[m]).map(m=>[m,D.methods[m].metrics])))}</section>`;
$('case-query').addEventListener('change',ev=>{selected=ev.target.value;renderCase();});$('left-method').addEventListener('change',ev=>{left=ev.target.value;renderCase();});$('right-method').addEventListener('change',ev=>{right=ev.target.value;renderCase();});document.querySelectorAll('[data-example]').forEach(b=>b.addEventListener('click',()=>{selected=b.dataset.example;renderCase();}));renderCase();}
render();
'''


def render(data):
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    for old, new in [('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')]:
        payload = payload.replace(old, new)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Chronoverse · Recipient delivery-time experiment</title><style>' + CSS + EXTRA_CSS + '</style></head><body>'
            '<header><div><a class="brand" href="#">chronoverse<span>DELIVERY RECEIPT EXPERIMENT</span></a><span class="local">Local synthetic diagnostic</span></div></header>'
            '<main><section class="intro"><div class="eyebrow">SAME WORLD. DIFFERENT RECEIPTS.</div><h1>Who received<br>which evidence, when?</h1>'
            '<p>A classical receipt-filtering experiment with fixed MiniLM and unchanged lexical/vector/graph ranking. No generated answers. Recipient receipt is separate from source perspective and factual correctness.</p></section>'
            '<div class="notice"><strong>Historical run, renamed schema.</strong> This report displays unchanged round-three numerical results through a delivery-schema migration. It is not a new inference run. <a href="migration-manifest.json">Old/new hashes and provenance</a>.</div><div id="content"></div><section class="panel"><h3>Recorded artifacts</h3><div class="report-links"><a href="README.md">Interpretation & reproduction</a><a href="PROTOCOL.md">Frozen protocol</a><a href="results.json" download>Full results JSON</a><a href="fixture.json" download>Frozen fixture JSON</a></div></section>'
            '<noscript><p>Enable JavaScript for the case explorer, or read the linked result JSON.</p></noscript><footer class="footer">Synthetic receipt semantics, not a claim of universal retrieval superiority.</footer></main>'
            '<script type="application/json" id="data">' + payload + '</script><script>' + JS + '</script></body></html>\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', type=Path, default=ROOT / 'docs/benchmarks-delivery')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/benchmarks-delivery/index.html')
    args = parser.parse_args()
    data = collect(args.input_dir)
    document = render(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document)
    print(json.dumps({'status': data['status'], 'output': str(args.output), 'bytes': len(document.encode())}))


if __name__ == '__main__':
    main()
