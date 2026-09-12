import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, Minus, Plus, RotateCcw } from 'lucide-react';
import type { Assertion, QueryResult } from './types';
import {
  buildIntegratedModel,
  intervalLabel,
  shortDate,
  timelineBounds,
  timelinePosition,
} from './integrated-views-model.mjs';
import './integrated-views.css';

type IntegratedViewsProps = {
  result: QueryResult;
  selected: string | null;
  onSelect: (id: string) => void;
  mode: 'graph-rag' | 'graph-rag-timeline';
};

type Point = { x: number; y: number };

const WIDTH = 1320;
const ROW_HEIGHT = 92;
const PIPELINE_TOP = 165;

const svgStyle = `
  .iv-bg{fill:#101218}.iv-grid{stroke:#292d37;stroke-width:1}.iv-stage{fill:#171a22;stroke:#343947;stroke-width:1}
  .iv-flow{fill:none;stroke:#596171;stroke-width:1.4}.iv-flow-accent{stroke:#aa91fa}.iv-box{fill:#1d212b;stroke:#424857;stroke-width:1.2}
  .iv-box-selected{fill:#29243a;stroke:#b69bff;stroke-width:2}.iv-source{fill:#192529;stroke:#3d6b6a}.iv-rank{fill:#242118;stroke:#76673b}
  .iv-entity{fill:#1a2028;stroke:#4f718b}.iv-title{fill:#f3f4f7;font:600 13px system-ui,sans-serif}.iv-copy{fill:#b9c0cc;font:11px system-ui,sans-serif}
  .iv-meta{fill:#858e9e;font:10px system-ui,sans-serif}.iv-label{fill:#9ca5b5;font:600 10px system-ui,sans-serif;letter-spacing:1.2px}
  .iv-score{fill:#f0cf77;font:600 12px ui-monospace,monospace}.iv-valid{stroke:#54c8b8;stroke-width:8;stroke-linecap:round}.iv-known{stroke:#b49afc;stroke-width:2}
  .iv-valid-inactive{stroke:#747b87;stroke-dasharray:7 6;opacity:.78}
  .iv-event{fill:#f0b45e;stroke:#101218;stroke-width:1}.iv-scope-valid{stroke:#54c8b8;stroke-width:1;stroke-dasharray:4 5}.iv-scope-known{stroke:#b49afc;stroke-width:1;stroke-dasharray:2 5}
  .iv-button{cursor:pointer}.iv-button:focus{outline:none}.iv-button:focus .iv-box,.iv-button:focus .iv-entity{stroke:#fff;stroke-width:2}
`;

function clampText(value: string, maximum: number) {
  return value.length > maximum ? `${value.slice(0, maximum - 1)}…` : value;
}

function activate(event: React.KeyboardEvent<SVGGElement>, action: () => void) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    action();
  }
}

function BoxText({ x, y, title, lines = [], meta }: { x: number; y: number; title: string; lines?: string[]; meta?: string }) {
  return <>
    <text x={x} y={y} className="iv-title">{clampText(title, 34)}</text>
    {lines.slice(0, 2).map((line, index) => <text key={`${line}-${index}`} x={x} y={y + 17 + index * 14} className="iv-copy">{clampText(line, 42)}</text>)}
    {meta && <text x={x} y={y + 36} className="iv-meta">{clampText(meta, 46)}</text>}
  </>;
}

function selectedClass(id: string, selected: string | null, base: string) {
  return `${base} ${id === selected ? 'iv-box-selected' : ''}`;
}

export function IntegratedViews({ result, selected, onSelect, mode }: IntegratedViewsProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [fit, setFit] = useState(false);
  const model = useMemo(() => buildIntegratedModel(result), [result]);
  const assertions = model.assertions as Assertion[];
  const pipelineHeight = Math.max(570, PIPELINE_TOP + assertions.length * ROW_HEIGHT + 25, PIPELINE_TOP + Math.ceil(model.graphNodes.length / 2) * 70 + 35);
  const hasTimeline = mode === 'graph-rag-timeline';
  const timelineTop = pipelineHeight + 70;
  const timelineHeight = hasTimeline ? Math.max(220, assertions.length * 78 + 120) : 0;
  const contentHeight = hasTimeline ? timelineTop + timelineHeight + 20 : pipelineHeight;
  const legendY = contentHeight + 23;
  const height = contentHeight + 72;
  const bounds = useMemo(() => timelineBounds(result, assertions), [result, assertions]);
  const graphNodePositions = useMemo(() => {
    const positions = new Map<string, Point>();
    model.graphNodes.forEach((node: { id: string }, index: number) => {
      const column = index % 2;
      const row = Math.floor(index / 2);
      positions.set(node.id, { x: 1020 + column * 190, y: PIPELINE_TOP + 34 + row * 70 });
    });
    return positions;
  }, [model.graphNodes]);

  const setZoomBounded = (next: number) => {
    setFit(false);
    setZoom(Math.max(0.7, Math.min(1.6, Number(next.toFixed(2)))));
  };

  const jumpTo = (section: 'evidence' | 'time', behavior: ScrollBehavior = 'smooth') => {
    const scroll = scrollRef.current;
    const canvas = svgRef.current;
    if (!scroll || !canvas) return;
    const scale = canvas.clientWidth / WIDTH;
    scroll.scrollTo({ left: 0, top: section === 'time' ? Math.max(0, (timelineTop - 60) * scale) : 0, behavior });
  };

  useEffect(() => {
    if (!hasTimeline) return;
    const frame = requestAnimationFrame(() => jumpTo('time', 'auto'));
    return () => cancelAnimationFrame(frame);
  }, [hasTimeline, timelineTop]);

  const exportSvg = () => {
    if (!svgRef.current) return;
    const clone = svgRef.current.cloneNode(true) as SVGSVGElement;
    clone.removeAttribute('style');
    clone.setAttribute('class', 'iv-canvas');
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('width', String(WIDTH));
    clone.setAttribute('height', String(height));
    const body = new XMLSerializer().serializeToString(clone);
    const url = URL.createObjectURL(new Blob([`<?xml version="1.0" encoding="UTF-8"?>\n${body}`], { type: 'image/svg+xml' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `chronoverse-${mode}.svg`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const graphRelationships = model.graphEdges.length as number;
  const countText = `Showing ${assertions.length} of ${model.totalAssertions} ranked assertions · ${model.passages.length} source passages · ${graphRelationships} of ${model.totalGraphEdges} graph relationships`;

  if (!assertions.length) {
    return <section className="integrated-view" aria-label="Integrated Graph-RAG view">
      <div className="iv-empty"><strong>No scoped results to project.</strong><span>Run a query or change the current time and knowledge scope.</span></div>
    </section>;
  }

  return <section className="integrated-view" aria-label={hasTimeline ? 'Integrated Graph-RAG and timeline view' : 'Integrated Graph-RAG view'}>
    <header className="iv-toolbar">
      <div>
        <strong>{hasTimeline ? 'Graph-RAG + two-clock timeline' : 'Graph-RAG evidence flow'}</strong>
        <span>{countText}</span>
      </div>
      <div className="iv-tools" aria-label="Diagram controls">
        {hasTimeline && <><button type="button" onClick={() => jumpTo('evidence')} aria-label="Jump to evidence flow">Evidence flow</button><button type="button" onClick={() => jumpTo('time')} aria-label="Jump to time lanes">Time lanes</button></>}
        <button type="button" onClick={() => setZoomBounded(zoom - 0.1)} aria-label="Zoom out"><Minus size={15}/></button>
        <output aria-label="Current zoom">{fit ? 'Fit' : `${Math.round(zoom * 100)}%`}</output>
        <button type="button" onClick={() => setZoomBounded(zoom + 0.1)} aria-label="Zoom in"><Plus size={15}/></button>
        <button type="button" onClick={() => setFit(true)} aria-label="Fit whole diagram to width">Fit</button>
        <button type="button" onClick={() => { setFit(false); setZoom(1); }} aria-label="Reset zoom"><RotateCcw size={15}/></button>
        <button type="button" onClick={exportSvg} aria-label="Export diagram as SVG"><Download size={15}/> SVG</button>
      </div>
    </header>
    <div className="iv-scope-note">
      Current filtered query only · {result.eligible_count} eligible at valid {shortDate(result.scope.valid_at)} / known {shortDate(result.scope.known_at)} · Scores show retrieval relevance, never truth confidence.
    </div>
    <div ref={scrollRef} className="iv-scroll" tabIndex={0} aria-label="Scrollable integrated diagram">
      <svg ref={svgRef} className={`iv-canvas ${fit ? 'is-fit' : ''}`} viewBox={`0 0 ${WIDTH} ${height}`} style={{ width: fit ? '100%' : `${WIDTH * zoom}px` }} role="img" aria-labelledby="iv-svg-title iv-svg-desc">
        <title id="iv-svg-title">{hasTimeline ? 'Chronoverse Graph-RAG evidence, graph, and bitemporal timeline' : 'Chronoverse Graph-RAG evidence and graph flow'}</title>
        <desc id="iv-svg-desc">Profile {result.profile_id || 'unspecified'}. Query: {result.query || '(all eligible assertions)'}. World {result.scope.world}, plane {result.scope.plane}, perspective {result.scope.perspective}. Valid at {result.scope.valid_at}; known at {result.scope.known_at}. Actual passages feed ranked retrieval results, assertions, and graph relationships for the current scoped query.</desc>
        <style>{svgStyle}</style>
        <defs>
          <pattern id="iv-grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M 24 0 L 0 0 0 24" className="iv-grid" fill="none"/></pattern>
          <marker id="iv-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#747d8d"/></marker>
        </defs>
        <rect width={WIDTH} height={height} className="iv-bg"/><rect width={WIDTH} height={height} fill="url(#iv-grid)" opacity=".45"/>

        <text x="40" y="28" className="iv-title">CHRONOVERSE · {hasTimeline ? 'GRAPH-RAG + TWO-CLOCK TIMELINE' : 'GRAPH-RAG EVIDENCE FLOW'}</text>
        <text x="40" y="49" className="iv-copy">Query: {clampText(result.query || '(all eligible assertions)', 115)}<title>{result.query || '(all eligible assertions)'}</title></text>
        <text x="40" y="67" className="iv-meta">Profile {clampText(result.profile_id || 'unspecified', 28)} · world {clampText(result.scope.world, 22)} · plane {clampText(result.scope.plane, 18)} · perspective {clampText(result.scope.perspective, 24)}</text>
        <text x="40" y="84" className="iv-meta">Valid at {result.scope.valid_at} · known at {result.scope.known_at}</text>
        <text x="990" y="84" className="iv-meta">{assertions.length}/{model.totalAssertions} assertions · {model.passages.length} passages · {graphRelationships}/{model.totalGraphEdges} relations</text>
        <line x1="40" x2="1280" y1="99" y2="99" className="iv-grid"/>
        <text x="40" y="122" className="iv-label">SOURCE PASSAGES</text>
        <text x="350" y="122" className="iv-label">RETRIEVAL / RANK</text>
        <text x="590" y="122" className="iv-label">SCOPED ASSERTIONS</text>
        <text x="990" y="122" className="iv-label">ENTITY GRAPH</text>
        <text x="40" y="143" className="iv-meta">Evidence recorded by selected known time</text>
        <text x="350" y="143" className="iv-meta">{clampText(result.retrieval.name, 31)} · relevance</text>
        <text x="590" y="143" className="iv-meta">Plane, lifecycle, valid interval</text>
        <text x="990" y="143" className="iv-meta">Current scoped graph projection</text>

        {assertions.map((assertion, index) => {
          const centerY = PIPELINE_TOP + index * ROW_HEIGHT + 34;
          const evidence = assertion.evidence.slice(0, 2);
          const passageYs = evidence.length === 2 ? [centerY - 20, centerY + 20] : [centerY];
          return <g key={`pipeline-${assertion.id}`}>
            {evidence.map((item, evidenceIndex) => <g key={`${assertion.id}:${item.id}`} data-assertion-id={assertion.id} data-evidence-id={item.id} className="iv-button" role="button" tabIndex={0} aria-label={`Inspect evidence ${item.title} for ${assertion.summary}`} onClick={() => onSelect(assertion.id)} onKeyDown={event => activate(event, () => onSelect(assertion.id))}>
              <path d={`M 290 ${passageYs[evidenceIndex]} C 315 ${passageYs[evidenceIndex]} 320 ${centerY} 350 ${centerY}`} className="iv-flow" markerEnd="url(#iv-arrow)"/>
              <rect x="40" y={passageYs[evidenceIndex] - 17} width="250" height="34" rx="7" className={selectedClass(assertion.id, selected, 'iv-box iv-source')}/>
              <text x="52" y={passageYs[evidenceIndex] - 2} className="iv-title">{clampText(item.title, 32)}</text>
              <text x="52" y={passageYs[evidenceIndex] + 11} className="iv-meta"><title>Evidence {item.id}; recorded {item.recorded_at}; {item.text}</title>{clampText(`${item.text} · ${shortDate(item.recorded_at)}${item.synthetic ? ' · synthetic' : ''}`, 35)}</text>
            </g>)}
            {!evidence.length && <g>
              <path d={`M 290 ${centerY} C 315 ${centerY} 320 ${centerY} 350 ${centerY}`} className="iv-flow" markerEnd="url(#iv-arrow)"/>
              <rect x="40" y={centerY - 17} width="250" height="34" rx="7" className="iv-box" strokeDasharray="4 4"/>
              <text x="52" y={centerY + 4} className="iv-meta">No visible evidence passage in this result</text>
            </g>}
            <g data-assertion-id={assertion.id} className="iv-button" role="button" tabIndex={0} aria-label={`Inspect rank ${index + 1}, relevance score ${assertion.score}`} onClick={() => onSelect(assertion.id)} onKeyDown={event => activate(event, () => onSelect(assertion.id))}>
              <path d={`M 540 ${centerY} L 590 ${centerY}`} className="iv-flow iv-flow-accent" markerEnd="url(#iv-arrow)"/>
              <rect x="350" y={centerY - 25} width="190" height="50" rx="8" className={selectedClass(assertion.id, selected, 'iv-box iv-rank')}/>
              <text x="365" y={centerY - 5} className="iv-label">RANK {String(index + 1).padStart(2, '0')}</text>
              <text x="365" y={centerY + 14} className="iv-score">{assertion.score.toFixed(3)}</text>
              <text x="427" y={centerY + 14} className="iv-meta">relevance</text>
            </g>
            <g data-assertion-id={assertion.id} className="iv-button" role="button" tabIndex={0} aria-label={`Inspect assertion ${assertion.subject} ${assertion.predicate} ${assertion.object}`} onClick={() => onSelect(assertion.id)} onKeyDown={event => activate(event, () => onSelect(assertion.id))}>
              <title>{assertion.id}: {assertion.subject} {assertion.predicate} {assertion.object}. Valid [{assertion.valid_from}, {assertion.effective_valid_to || assertion.valid_to || 'open'}); recorded {assertion.recorded_at}; status {assertion.status}.</title>
              <rect x="590" y={centerY - 32} width="330" height="64" rx="9" className={selectedClass(assertion.id, selected, 'iv-box')}/>
              <BoxText x={605} y={centerY - 11} title={assertion.subject} lines={[`${assertion.predicate.replaceAll('_', ' ')} → ${assertion.object}`]} meta={`${assertion.plane} · ${assertion.status} · ${intervalLabel(assertion)}`}/>
            </g>
          </g>;
        })}

        {model.graphEdges.map((edge: QueryResult['graph']['edges'][number], index: number) => {
          const source = graphNodePositions.get(edge.source);
          const target = graphNodePositions.get(edge.target);
          const assertionIndex = assertions.findIndex(item => item.id === edge.assertion_id);
          if (!source || !target || assertionIndex < 0) return null;
          const assertionY = PIPELINE_TOP + assertionIndex * ROW_HEIGHT + 34;
          const midX = (source.x + target.x) / 2;
          const midY = (source.y + target.y) / 2;
          return <g key={edge.id} data-assertion-id={edge.assertion_id} data-graph-edge-id={edge.id} className="iv-button" role="button" tabIndex={0} aria-label={`Inspect relationship ${edge.label}`} onClick={() => onSelect(edge.assertion_id)} onKeyDown={event => activate(event, () => onSelect(edge.assertion_id))}>
            <path d={`M 920 ${assertionY} C 950 ${assertionY} 950 ${source.y} ${source.x - 49} ${source.y}`} className={edge.assertion_id === selected ? 'iv-flow iv-flow-accent' : 'iv-flow'}/>
            <path d={`M ${source.x + 49} ${source.y} Q ${midX} ${midY - 18} ${target.x - 49} ${target.y}`} className={edge.assertion_id === selected ? 'iv-flow iv-flow-accent' : 'iv-flow'} markerEnd="url(#iv-arrow)"/>
            <rect x={midX - 44} y={midY - 22} width="88" height="17" rx="4" className="iv-stage"/><text x={midX} y={midY - 10} textAnchor="middle" className="iv-meta">{clampText(edge.label.replaceAll('_', ' '), 16)}</text>
          </g>;
        })}
        {model.graphNodes.map((node: QueryResult['graph']['nodes'][number]) => {
          const point = graphNodePositions.get(node.id)!;
          const related = model.graphEdges.find((edge: QueryResult['graph']['edges'][number]) => edge.source === node.id || edge.target === node.id);
          return <g key={node.id} className="iv-button" role={related ? 'button' : undefined} tabIndex={related ? 0 : undefined} aria-label={`Graph entity ${node.label}`} onClick={() => related && onSelect(related.assertion_id)} onKeyDown={event => related && activate(event, () => onSelect(related.assertion_id))}>
            <rect x={point.x - 49} y={point.y - 22} width="98" height="44" rx="17" className={related ? selectedClass(related.assertion_id, selected, 'iv-entity') : 'iv-entity'}/>
            <text x={point.x} y={point.y - 2} textAnchor="middle" className="iv-title">{clampText(node.label, 12)}</text><text x={point.x} y={point.y + 12} textAnchor="middle" className="iv-meta">{clampText(node.kind, 12)}</text>
          </g>;
        })}

        {hasTimeline && <g aria-label="Bitemporal lanes">
          <rect x="28" y={timelineTop - 54} width={WIDTH - 56} height={timelineHeight + 45} rx="12" className="iv-stage"/>
          <text x="48" y={timelineTop - 21} className="iv-label">GRAPH-RAG-TIMELINE · TWO CLOCKS</text>
          <text x="48" y={timelineTop + 2} className="iv-meta">The interval is the stored/effective valid window; status says whether the assertion is active at this query snapshot. Other marks show when the ledger learned changes.</text>
          <text x="350" y={timelineTop + 25} className="iv-meta">{shortDate(new Date(bounds.min).toISOString())}</text>
          <text x="1240" y={timelineTop + 25} textAnchor="end" className="iv-meta">{shortDate(new Date(bounds.max).toISOString())}</text>
          <line x1={350 + timelinePosition(result.scope.valid_at, bounds) * 890} x2={350 + timelinePosition(result.scope.valid_at, bounds) * 890} y1={timelineTop + 34} y2={timelineTop + assertions.length * 78 + 45} className="iv-scope-valid"><title>Selected valid_at {result.scope.valid_at}</title></line>
          <line x1={350 + timelinePosition(result.scope.known_at, bounds) * 890} x2={350 + timelinePosition(result.scope.known_at, bounds) * 890} y1={timelineTop + 34} y2={timelineTop + assertions.length * 78 + 45} className="iv-scope-known"><title>Selected known_at {result.scope.known_at}</title></line>
          {assertions.map((assertion, index) => {
            const y = timelineTop + 56 + index * 78;
            const start = 350 + timelinePosition(assertion.valid_from, bounds) * 890;
            const endValue = assertion.effective_valid_to || assertion.valid_to;
            const end = endValue ? 350 + timelinePosition(endValue, bounds) * 890 : 1240;
            const recorded = 350 + timelinePosition(assertion.recorded_at, bounds) * 890;
            return <g key={`timeline-${assertion.id}`} data-assertion-id={assertion.id} className="iv-button" role="button" tabIndex={0} aria-label={`Inspect timeline for ${assertion.summary}`} onClick={() => onSelect(assertion.id)} onKeyDown={event => activate(event, () => onSelect(assertion.id))}>
              <rect x="42" y={y - 25} width="1206" height="68" rx="7" className={assertion.id === selected ? 'iv-box-selected' : 'iv-bg'} opacity={assertion.id === selected ? 1 : .65}/>
              <text x="55" y={y - 5} className="iv-title">{clampText(assertion.subject, 33)}</text>
              <text x="55" y={y + 12} className="iv-copy">{clampText(assertion.object, 35)}</text>
              <text x="55" y={y + 29} className="iv-meta"><title>Status {assertion.status} at this query snapshot. Stored/effective valid window [{assertion.valid_from}, {endValue || 'open'}); recorded {assertion.recorded_at}</title>{intervalLabel(assertion)} · {assertion.status}</text>
              <line x1="350" x2="1240" y1={y} y2={y} className="iv-grid"/>
              <line x1={start} x2={Math.max(start + 3, end)} y1={y - 7} y2={y - 7} className={assertion.status === 'active' ? 'iv-valid' : 'iv-valid iv-valid-inactive'}><title>Status {assertion.status} at this query snapshot. Stored/effective valid window [{assertion.valid_from}, {endValue || 'open'})</title></line>
              <line x1={recorded} x2={recorded} y1={y + 7} y2={y + 28} className="iv-known"><title>Recorded {assertion.recorded_at}</title></line>
              <circle cx={recorded} cy={y + 28} r="4" fill="#b49afc"><title>Assertion recorded {assertion.recorded_at}</title></circle>
              {assertion.events.map((event, eventIndex) => {
                const effectiveX = 350 + timelinePosition(event.effective_at, bounds) * 890;
                const recordedX = 350 + timelinePosition(event.recorded_at, bounds) * 890;
                return <g key={event.id}>
                  <path d={`M ${effectiveX} ${y - 17} l 6 6 l -6 6 l -6 -6 z`} className="iv-event"><title>{event.type}: effective {event.effective_at}</title></path>
                  <line x1={effectiveX} x2={recordedX} y1={y + 18 + eventIndex * 3} y2={y + 18 + eventIndex * 3} stroke="#8e744c" strokeDasharray="3 3"><title>{event.type}: effective {event.effective_at}; recorded {event.recorded_at}</title></line>
                  <circle cx={recordedX} cy={y + 18 + eventIndex * 3} r="4" className="iv-event"><title>{event.type} recorded {event.recorded_at}: {event.reason}</title></circle>
                  <text x={Math.min(1180, recordedX + 7)} y={y + 15 + eventIndex * 12} className="iv-meta">{event.type} · {shortDate(event.recorded_at)}</text>
                </g>;
              })}
            </g>;
          })}
        </g>}
        <g aria-label="Diagram legend">
          <line x1="40" x2="1280" y1={legendY - 16} y2={legendY - 16} className="iv-grid"/>
          <text x="40" y={legendY + 4} className="iv-label">LEGEND</text>
          <rect x="112" y={legendY - 8} width="14" height="10" rx="2" className="iv-source"/><text x="133" y={legendY + 2} className="iv-meta">source passage</text>
          <rect x="252" y={legendY - 8} width="14" height="10" rx="2" className="iv-rank"/><text x="273" y={legendY + 2} className="iv-meta">retrieval relevance</text>
          <rect x="410" y={legendY - 8} width="14" height="10" rx="2" className="iv-box-selected"/><text x="431" y={legendY + 2} className="iv-meta">assertion / selected</text>
          <rect x="571" y={legendY - 8} width="14" height="10" rx="5" className="iv-entity"/><text x="592" y={legendY + 2} className="iv-meta">entity / relation</text>
          {hasTimeline && <><line x1="710" x2="728" y1={legendY - 3} y2={legendY - 3} className="iv-valid"/><text x="737" y={legendY + 2} className="iv-meta">active window</text><line x1="830" x2="848" y1={legendY - 3} y2={legendY - 3} className="iv-valid iv-valid-inactive"/><text x="857" y={legendY + 2} className="iv-meta">inactive history</text><line x1="967" x2="967" y1={legendY - 10} y2={legendY + 3} className="iv-known"/><text x="976" y={legendY + 2} className="iv-meta">recorded</text><path d={`M 1055 ${legendY - 9} l 6 6 l -6 6 l -6 -6 z`} className="iv-event"/><text x="1068" y={legendY + 2} className="iv-meta">lifecycle event</text></>}
          <text x="40" y={legendY + 24} className="iv-meta">Current scoped query only · relevance is not truth confidence · {model.omittedAssertions + model.omittedPassages + model.omittedGraphEdges} visible records omitted by diagram limits</text>
        </g>
      </svg>
    </div>
    <footer className="iv-legend">
      <span><i className="iv-key passage"/> source passage</span><span><i className="iv-key rank"/> retrieval relevance</span><span><i className="iv-key assertion"/> assertion</span><span><i className="iv-key entity"/> entity / relation</span>
      {hasTimeline && <><span><i className="iv-key valid"/> active valid window</span><span><i className="iv-key inactive"/> inactive historical window</span><span><i className="iv-key recorded"/> recorded</span><span><i className="iv-key event"/> lifecycle event</span></>}
      {(model.omittedAssertions > 0 || model.omittedPassages > 0 || model.omittedGraphEdges > 0) && <strong>Bounded for legibility: {model.omittedAssertions} assertions, {model.omittedPassages} passages, {model.omittedGraphEdges} relationships omitted.</strong>}
    </footer>
    <p className="iv-disclaimer">This view visualizes the current Chronoverse query response. It does not claim exhaustive history or reproduce the Microsoft GraphRAG algorithm.</p>
  </section>;
}
