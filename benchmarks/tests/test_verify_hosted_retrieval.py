from copy import deepcopy
import pytest
from benchmarks.verify_hosted_retrieval import verify


def sample():
    model = {'model': 'text-embedding-3-large', 'dimensions': 3072,
             'max_input_tokens': 512, 'tokenizer': 'cl100k_base'}
    return {'status': 'complete', 'dataset': {
        'corpus_count': 2, 'query_count': 1, 'rankings': {'q': ['a', 'b']},
        'per_query_ndcg': {'q': 1.0}, 'nDCG@10': 1.0,
        'document_embeddings': model, 'query_embeddings': model},
        'provenance': {'git_dirty': False, 'predictions_committed_exactly': True,
                       'git_commit': 'abc', 'predictions_commit': 'def', 'predictions_sha256': 'ghi'},
        'accounting': {'reserved_tokens': 100, 'calls': {'one': {
            'status': 'complete', 'reserved_tokens': 100, 'response_model': 'text-embedding-3-large',
            'usage': {'total_tokens': 10}}}}}


def test_independent_metric_reconstruction():
    result = sample()
    original = deepcopy(result)
    assert verify(result, {'a', 'b'}, {'q': {'a': 2}})['nDCG@10'] == 1.0
    assert result == original


def test_recovered_timeout_remains_an_unknown_prior_charge():
    result = sample()
    call = result['accounting']['calls']['one']
    call.update(current_reservation=60, prior_attempts=[{
        'status': 'failed_or_uncertain', 'error_type': 'TimeoutError', 'reserved_tokens': 40}])
    summary = verify(result, {'a', 'b'}, {'q': {'a': 2}})
    assert summary['prior_uncertain_attempts'] == 1
    assert summary['unresolved_requests'] == 1
    assert summary['cumulative_observed_tokens'] == 10


def test_only_guarded_generated_results_may_be_dirty():
    result = sample()
    result['provenance'].update(git_dirty=True, allow_dirty=False,
        generated_outputs_dirty_exemption=True,
        git_dirty_paths=['docs/benchmarks-next/hosted-scifact-results.json'],
        generated_outputs=['docs/benchmarks-next/hosted-scifact-results.json'])
    verify(result, {'a', 'b'}, {'q': {'a': 2}})
    result['provenance']['git_dirty_paths'].append('benchmarks/hosted_retrieval.py')
    with pytest.raises(AssertionError): verify(result, {'a', 'b'}, {'q': {'a': 2}})


@pytest.mark.parametrize('corruption', ['aggregate', 'per_query', 'ranking', 'accounting', 'model'])
def test_corrupt_artifact_fails(corruption):
    result = sample()
    if corruption == 'aggregate': result['dataset']['nDCG@10'] = .9
    if corruption == 'per_query': result['dataset']['per_query_ndcg']['q'] = .9
    if corruption == 'ranking': result['dataset']['rankings']['q'] = ['a', 'a']
    if corruption == 'accounting': result['accounting']['reserved_tokens'] = 99
    if corruption == 'model': result['accounting']['calls']['one']['response_model'] = 'another'
    with pytest.raises(AssertionError): verify(result, {'a', 'b'}, {'q': {'a': 2}})
