import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildIntegratedModel,
  intervalLabel,
  timelineBounds,
} from './integrated-views-model.mjs';

function assertion(index, overrides = {}) {
  const id = `a-${index}`;
  return {
    id,
    subject: `Subject ${index}`,
    predicate: 'relates_to',
    object: `Object ${index}`,
    world: 'shared',
    plane: 'fact',
    perspective: 'public',
    valid_from: '2026-01-01T00:00:00Z',
    valid_to: null,
    recorded_at: '2026-01-03T00:00:00Z',
    status: 'active',
    effective_valid_to: null,
    summary: `Assertion ${index}`,
    evidence: [{
      id: `e-${index}`,
      title: `Source ${index}`,
      url: null,
      text: `Passage ${index}`,
      recorded_at: '2026-01-03T00:00:00Z',
      synthetic: false,
    }],
    events: [],
    score: 1 - index / 100,
    score_breakdown: { lexical: 0.3, vector: 0.2, graph: 0.1 },
    explanation: 'Fixture',
    ...overrides,
  };
}

function result(results) {
  return {
    query: 'history',
    scope: {
      valid_at: '2026-02-01T00:00:00Z',
      known_at: '2026-02-10T00:00:00Z',
      world: 'shared',
      plane: 'fact',
      perspective: 'public',
    },
    results,
    conflicts: [],
    graph: {
      nodes: [
        { id: 'n-0', label: 'Subject 0', kind: 'entity' },
        { id: 'n-1', label: 'Object 0', kind: 'entity' },
        { id: 'unused', label: 'Outside bounded results', kind: 'entity' },
      ],
      edges: [
        { id: 'g-0', source: 'n-0', target: 'n-1', label: 'relates_to', assertion_id: 'a-0', plane: 'fact', status: 'active' },
        { id: 'g-unused', source: 'unused', target: 'n-1', label: 'old', assertion_id: 'a-99', plane: 'fact', status: 'retired' },
      ],
    },
    explanation: 'Scoped fixture',
    eligible_count: results.length,
    retrieval: { name: 'Hybrid retrieval', description: 'Relevance ranking' },
  };
}

test('integrated view bounds large result sets and graph edges to visible assertions', () => {
  const data = result(Array.from({ length: 14 }, (_, index) => assertion(index)));
  const model = buildIntegratedModel(data);

  assert.equal(model.assertions.length, 12);
  assert.equal(model.totalAssertions, 14);
  assert.equal(model.passages.length, 12);
  assert.deepEqual(model.graphEdges.map(edge => edge.id), ['g-0']);
  assert.deepEqual(model.graphNodes.map(node => node.id), ['n-0', 'n-1']);
  assert.equal(model.assertions[0].score, 1);
});

test('timeline bounds include both valid and recorded lifecycle clocks', () => {
  const corrected = assertion(0, {
    valid_from: '2026-01-02T00:00:00Z',
    effective_valid_to: '2026-01-20T00:00:00Z',
    recorded_at: '2026-01-08T00:00:00Z',
    events: [{
      id: 'ev-1', assertion_id: 'a-0', type: 'correct',
      effective_at: '2025-12-28T00:00:00Z',
      recorded_at: '2026-03-04T00:00:00Z', reason: 'Late correction',
      source: 'gazette', replacement_id: null,
    }],
  });

  const bounds = timelineBounds(result([corrected]), [corrected]);
  assert.equal(new Date(bounds.min).toISOString(), '2025-12-28T00:00:00.000Z');
  assert.equal(new Date(bounds.max).toISOString(), '2026-03-04T00:00:00.000Z');
  assert.equal(intervalLabel(corrected), '[2026-01-02, 2026-01-20)');
  assert.equal(intervalLabel(assertion(1)), '[2026-01-01, open)');
});

test('dense graph projections have an explicit relationship ceiling', () => {
  const data = result([assertion(0)]);
  data.graph.nodes = Array.from({ length: 21 }, (_, index) => ({ id: `n-${index}`, label: `Node ${index}`, kind: 'entity' }));
  data.graph.edges = Array.from({ length: 20 }, (_, index) => ({
    id: `edge-${index}`, source: `n-${index}`, target: `n-${index + 1}`,
    label: 'links', assertion_id: 'a-0', plane: 'fact', status: 'active',
  }));

  const model = buildIntegratedModel(data);
  assert.equal(model.graphEdges.length, 18);
  assert.equal(model.totalGraphEdges, 20);
  assert.equal(model.omittedGraphEdges, 2);
});
