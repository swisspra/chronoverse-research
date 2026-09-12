export const MAX_INTEGRATED_ASSERTIONS = 12;
export const MAX_PASSAGES_PER_ASSERTION = 2;
export const MAX_GRAPH_EDGES = 18;

/**
 * Keep an integrated projection legible while preserving the API rank order.
 * Geometry is assigned by the React view; this model never invents embedding
 * coordinates or truth confidence.
 */
export function buildIntegratedModel(result) {
  const assertions = result.results.slice(0, MAX_INTEGRATED_ASSERTIONS);
  const visibleIds = new Set(assertions.map(item => item.id));
  const passages = assertions.flatMap(assertion =>
    assertion.evidence.slice(0, MAX_PASSAGES_PER_ASSERTION).map(evidence => ({
      key: `${assertion.id}:${evidence.id}`,
      assertionId: assertion.id,
      evidence,
    })),
  );
  const eligibleGraphEdges = result.graph.edges.filter(edge => visibleIds.has(edge.assertion_id));
  const graphEdges = eligibleGraphEdges.slice(0, MAX_GRAPH_EDGES);
  const nodeIds = new Set(graphEdges.flatMap(edge => [edge.source, edge.target]));
  const graphNodes = result.graph.nodes.filter(node => nodeIds.has(node.id));

  return {
    assertions,
    passages,
    graphEdges,
    graphNodes,
    totalAssertions: result.results.length,
    totalGraphEdges: eligibleGraphEdges.length,
    omittedGraphEdges: Math.max(0, eligibleGraphEdges.length - graphEdges.length),
    omittedAssertions: Math.max(0, result.results.length - assertions.length),
    omittedPassages: assertions.reduce(
      (total, assertion) => total + Math.max(0, assertion.evidence.length - MAX_PASSAGES_PER_ASSERTION),
      0,
    ),
  };
}

const parsed = value => {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
};

export function timelineBounds(result, assertions) {
  const timestamps = [parsed(result.scope.valid_at), parsed(result.scope.known_at)];
  for (const assertion of assertions) {
    timestamps.push(
      parsed(assertion.valid_from),
      parsed(assertion.effective_valid_to || assertion.valid_to),
      parsed(assertion.recorded_at),
    );
    for (const event of assertion.events) {
      timestamps.push(parsed(event.effective_at), parsed(event.recorded_at));
    }
  }
  const finite = timestamps.filter(value => value !== null);
  const fallback = Date.parse('2000-01-01T00:00:00Z');
  const min = finite.length ? Math.min(...finite) : fallback;
  let max = finite.length ? Math.max(...finite) : fallback + 86_400_000;
  if (max <= min) max = min + 86_400_000;
  return { min, max };
}

export function timelinePosition(value, bounds) {
  const timestamp = parsed(value);
  if (timestamp === null) return 0;
  return Math.max(0, Math.min(1, (timestamp - bounds.min) / (bounds.max - bounds.min)));
}

export function shortDate(value) {
  return value ? value.slice(0, 10) : 'open';
}

export function intervalLabel(assertion) {
  return `[${shortDate(assertion.valid_from)}, ${shortDate(assertion.effective_valid_to || assertion.valid_to)})`;
}
