from benchmarks.generate_temporal import generate
from benchmarks.temporal import summarize_run


def test_empty_gold_is_separate_from_answerable_recall():
    fixture=generate()
    answerable=next(q for q in fixture['queries'] if q['category']=='late_correction_after')
    empty=next(q for q in fixture['queries'] if q['category']=='retraction_empty')
    fixture['queries']=[answerable,empty]
    result=summarize_run({answerable['id']:answerable['gold_assertion_ids'],empty['id']:[]},fixture)
    assert result['query_count']==1
    assert result['total_query_count']==2
    assert result['recall@10']==1
    assert result['empty_gold_abstention_rate']==1
    assert result['exact_set@10_all_queries']==1


def test_perfect_first_answer_can_still_return_retired_evidence():
    fixture=generate()
    query=next(q for q in fixture['queries'] if q['category']=='late_correction_after')
    event=next(e for e in fixture['events'] if e['replacement_id']==query['gold_assertion_ids'][0])
    fixture['queries']=[query]
    result=summarize_run({query['id']:[*query['gold_assertion_ids'],event['assertion_id']]},fixture)
    assert result['ndcg@10']==1
    assert result['returned_set_precision@10_answerable']==0.5
    assert result['coordinate_ineligible_fraction@10']==0.5
    assert result['exact_set@10_all_queries']==0


def test_unknown_ids_do_not_silently_escape_violation_count():
    fixture=generate()
    fixture['queries']=fixture['queries'][:1]
    query=fixture['queries'][0]
    result=summarize_run({query['id']:['missing']},fixture)
    assert result['coordinate_ineligible_fraction@10']==1
