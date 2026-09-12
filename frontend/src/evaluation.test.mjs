import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('renders the actual evaluator object query without crashing and preserves temporal coordinates', async () => {
  // Captured from POST /api/evaluate: full QueryRequest objects, not query strings.
  const fixture = JSON.parse(await readFile(new URL('./fixtures/evaluation.json', import.meta.url), 'utf8'));
  const server = await createServer({server: {middlewareMode: true}, appType: 'custom', optimizeDeps: {noDiscovery: true, include: []}});
  try {
    const { EvaluationResults } = await server.ssrLoadModule('/src/Evaluation.tsx');
    const html = renderToStaticMarkup(React.createElement(EvaluationResults, {result: fixture}));
    assert.match(html, /Harbor director/);
    assert.match(html, /2026-07-05T00:00:00/);
    assert.match(html, /2026-07-06T00:00:00/);
    assert.match(html, /Conflicting reports stay visible/);
    assert.doesNotMatch(html, /\[object Object\]/);
  } finally {await server.close();}
});
