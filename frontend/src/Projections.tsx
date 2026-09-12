import { useMemo } from 'react';
import { CircleDot, Network, ScanLine } from 'lucide-react';
import type { Assertion, QueryResult } from './types';

const shortDate = (value: string | null) => value ? value.slice(0, 10) : 'Open';

export function GraphView({ data, selected, onSelect }: { data: QueryResult; selected: string | null; onSelect: (id: string) => void }) {
  const graphHeight = Math.max(430, (Math.max(new Set(data.graph.edges.map(edge => edge.source)).size, data.graph.nodes.length - new Set(data.graph.edges.map(edge => edge.source)).size)) * 85 + 100);
  const nodes = useMemo(() => {
    const sourceIds = new Set(data.graph.edges.map(edge => edge.source));
    const sources = data.graph.nodes.filter(node => sourceIds.has(node.id));
    const targets = data.graph.nodes.filter(node => !sourceIds.has(node.id));
    return data.graph.nodes.map(node => {
      const isSource = sourceIds.has(node.id), group = isSource ? sources : targets;
      const index = group.findIndex(item => item.id === node.id);
      const x = sources.length === 1 && targets.length > 1 ? (isSource ? 225 : 550) : (isSource ? 190 : 560);
      return {...node, x: x + (isSource ? 0 : Math.sin(index * 2) * 40), y: 62 + ((index + 0.5) / Math.max(group.length, 1)) * (graphHeight - 124), isSource};
    });
  }, [data.graph, graphHeight]);
  const nodeMap = new Map(nodes.map(node => [node.id, node]));
  return <div className="graph-stage" data-testid="graph-view">
    <div className="graph-caption"><span className="live-dot lilac"/> Scoped graph projection <span>{data.graph.nodes.length} entities · {data.graph.edges.length} assertions</span></div>
    <div className="graph-scroll"><svg className="knowledge-graph" style={{aspectRatio:`780 / ${graphHeight}`}} viewBox={`0 0 780 ${graphHeight}`} role="group" aria-label="Knowledge graph. Select an entity or relationship to inspect its assertion.">
      <defs><pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.8" fill="#343942" /></pattern><radialGradient id="graphGlow"><stop stopColor="#b49afc" stopOpacity="0.09"/><stop offset="1" stopColor="#b49afc" stopOpacity="0"/></radialGradient><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#81789d"/></marker></defs>
      <rect width="780" height={graphHeight} fill="url(#dots)"/><ellipse cx="390" cy="220" rx="330" ry="205" fill="url(#graphGlow)"/>
      {data.graph.edges.map((edge, index) => {
        const source = nodeMap.get(edge.source), target = nodeMap.get(edge.target);
        if (!source || !target) return null;
        const active = edge.assertion_id === selected;
        const midX = (source.x + target.x) / 2, midY = (source.y + target.y) / 2;
        return <g key={edge.id} className={`graph-edge ${active ? 'selected' : ''}`} tabIndex={0} role="button" aria-label={`Inspect ${source.label} ${edge.label} ${target.label}`} onClick={() => onSelect(edge.assertion_id)} onKeyDown={event => {if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(edge.assertion_id); }}} data-testid={`graph-edge-${index}`}>
          <path d={`M ${source.x + 21} ${source.y} Q ${midX} ${midY - 20} ${target.x - 23} ${target.y}`} className="edge-hit"/>
          <path d={`M ${source.x + 21} ${source.y} Q ${midX} ${midY - 20} ${target.x - 23} ${target.y}`} markerEnd="url(#arrow)" className="edge-line"/>
          <rect x={midX - 69} y={midY - 24} width="138" height="23" rx="5" className="edge-label-bg"/><text x={midX} y={midY - 9} textAnchor="middle" className="edge-label">{edge.label.replaceAll('_', ' ').slice(0, 24)}</text>
        </g>;
      })}
      {nodes.map((node, index) => {
        const related = data.graph.edges.filter(edge => edge.source === node.id || edge.target === node.id);
        const active = related.some(edge => edge.assertion_id === selected);
        return <g key={node.id} className={`graph-node ${active ? 'selected' : ''}`} role="button" tabIndex={0} aria-label={`Inspect ${node.label}`} onClick={() => related[0] && onSelect(related[0].assertion_id)} onKeyDown={event => {if ((event.key === 'Enter' || event.key === ' ') && related[0]) {event.preventDefault(); onSelect(related[0].assertion_id);}}} data-testid={`graph-node-${index}`}>
          <circle cx={node.x} cy={node.y} r="28" className="node-aura"/><circle cx={node.x} cy={node.y} r="20" className={node.isSource ? 'node-core source' : 'node-core'}/><circle cx={node.x} cy={node.y} r="6" fill={node.isSource ? '#c0a8ff' : '#74d5cd'}/>
          <text x={node.x} y={node.y + 42} textAnchor="middle" className="node-label">{node.label.length > 33 ? `${node.label.slice(0, 31)}…` : node.label}</text>
          <text x={node.x} y={node.y + 57} textAnchor="middle" className="node-kind">{node.isSource ? 'SUBJECT' : 'OBJECT'}</text>
        </g>;
      })}
    </svg></div>
    <div className="graph-footer"><span><CircleDot size={12}/> Select any node or connection to follow its evidence</span><span>Filtered before expansion</span></div>
  </div>;
}

export function VectorView({ data, selected, onSelect }: { data: QueryResult; selected: string | null; onSelect: (id: string) => void }) {
  const maximum = Math.max(...data.results.map(item => item.score_breakdown?.vector ?? 0), 0.001);
  return <div className="vector-view"><div className="projection-intro"><ScanLine size={20}/><div><h3>Similarity, with the math visible.</h3><p>{data.retrieval.description} Retrieval scores measure relevance, never truth.</p></div></div>
    <div className="vector-columns"><span>Assertion</span><span>{data.retrieval.name.includes('semantic') ? 'Semantic' : 'Lexical'} vector similarity</span></div>
    {data.results.map((item, index) => <button className={`vector-row ${selected === item.id ? 'selected' : ''}`} key={item.id} onClick={() => onSelect(item.id)}><span className="vector-rank">{String(index + 1).padStart(2, '0')}</span><span className="vector-name">{item.subject}<small>{item.predicate} → {item.object}</small></span><span className="vector-bar"><span style={{width: `${Math.max(1, (item.score_breakdown?.vector ?? 0) / maximum * 100)}%`}}/></span><code>{(item.score_breakdown?.vector ?? 0).toFixed(3)}</code></button>)}
    <p className="projection-note">Bars are scaled to the highest vector score in this result set. {data.explanation}</p></div>;
}

export function TimelineView({ data, selected, onSelect }: {data: QueryResult; selected: string | null; onSelect: (id: string) => void}) {
  const timestamps = data.results.flatMap(item => [Date.parse(item.valid_from), Date.parse(item.effective_valid_to || data.scope.valid_at), Date.parse(item.recorded_at)]).filter(Number.isFinite);
  const min = Math.min(...timestamps, Date.parse(data.scope.valid_at)), max = Math.max(...timestamps, Date.parse(data.scope.known_at)), span = Math.max(max - min, 86400000);
  const position = (value: string) => Math.min(97, Math.max(1, (Date.parse(value) - min) / span * 96 + 1));
  return <div className="timeline-view"><div className="projection-intro amber"><Network size={20}/><div><h3>Two clocks. One explainable history.</h3><p>Valid time is when a claim applies. Knowledge time is when the ledger learned it.</p></div></div><div className="timeline-legend"><span><i className="valid-mark"/> Valid interval [from, to)</span><span><i className="known-mark"/> Recorded in ledger</span></div>
    <div className="timeline-axis"><span>{shortDate(new Date(min).toISOString())}</span><span>{shortDate(new Date(max).toISOString())}</span></div>
    {data.results.map(item => <button className={`timeline-row ${selected === item.id ? 'selected' : ''}`} key={item.id} onClick={() => onSelect(item.id)}><span>{item.subject}<small>{item.object}</small></span><div className="time-track"><i className="time-interval" style={{left:`${position(item.valid_from)}%`, width:`${Math.max(0.7, (item.effective_valid_to ? position(item.effective_valid_to) : 99) - position(item.valid_from))}%`}}/><i className="time-record" style={{left:`${position(item.recorded_at)}%`}}/><i className="time-cursor" style={{left:`${position(data.scope.valid_at)}%`}}/></div><small>{shortDate(item.valid_from)} → {shortDate(item.effective_valid_to)}</small></button>)}
    <p className="projection-note">Dashed line: selected valid time. Dates are UTC; open intervals extend beyond this view. This projection shows eligible search results, including retired assertions only when enabled.</p></div>;
}

export function AssertionList({items, selected, onSelect}: {items: Assertion[]; selected: string | null; onSelect: (id: string) => void}) {
  return <div className="assertion-list">{items.map((item, index) => <button className={`assertion-row ${selected === item.id ? 'selected' : ''}`} key={item.id} onClick={() => onSelect(item.id)} data-testid={`assertion-row-${index}`}><span className="row-number">{String(index + 1).padStart(2,'0')}</span><span className="assertion-statement"><strong>{item.subject} <span>{item.predicate.replaceAll('_', ' ')}</span> {item.object}</strong><small>{item.evidence[0]?.title || 'Evidence available'} · {item.perspective}</small></span><span className={`plane-pill ${item.plane}`}>{item.plane}</span><span className={`status ${item.status}`}><i/>{item.status}</span><code className="row-score" title="Combined relevance score, not truth confidence">{item.score.toFixed(3)}</code></button>)}</div>;
}
