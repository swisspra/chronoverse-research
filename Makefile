.PHONY: dev lexical test build verify
dev:
	./scripts/dev.sh
lexical:
	./scripts/dev.sh --lexical
test:
	uv run --project backend --group dev pytest backend/tests -q
build:
	npm ci --prefix frontend
	npm run build --prefix frontend
verify:
	backend/.venv/bin/python -m pytest backend/tests -q
	.bench-venv/bin/python -m pytest benchmarks -q
	.bench-venv/bin/python -m benchmarks.verify_v2_artifacts
	.bench-venv/bin/python -m benchmarks.verify_delivery_experiment
	.bench-venv/bin/python -m benchmarks.verify_delivery_v3
	.bench-venv/bin/python -m benchmarks.verify_openrouter_rerank docs/benchmarks-next/openrouter-rerank-results.json
	.bench-venv/bin/python -m benchmarks.verify_answer_full500 docs/benchmarks-next/answer-full500
	.bench-mps-venv/bin/python -m benchmarks.verify_longmemeval_rag --results docs/benchmarks-longmemeval/results.json.gz --contexts docs/benchmarks-longmemeval/contexts.jsonl.gz
	.bench-venv/bin/python -m benchmarks.verify_fantom
	.bench-venv/bin/python -m benchmarks.verify_cross_domain_v3 docs/benchmarks-v3/cross-domain-results.json.gz
	.bench-venv/bin/python -m benchmarks.verify_hosted_retrieval docs/benchmarks-next/hosted-scifact-results.json --corpus-dir .benchmark-data/v2/scifact/scifact
	.bench-venv/bin/python -m benchmarks.verify_hosted_retrieval docs/benchmarks-next/hosted-nfcorpus-results.json --corpus-dir .benchmark-data/v2/nfcorpus/nfcorpus
	.bench-venv/bin/python -m benchmarks.verify_hosted_retrieval docs/benchmarks-next/hosted-fiqa-results.json --corpus-dir .benchmark-data/v2/fiqa/fiqa
	npm test --prefix frontend
	npm run build --prefix frontend
