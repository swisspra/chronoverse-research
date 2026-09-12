"""Gold isolation and mapping tests; no real FANToM label scoring here."""
from copy import deepcopy
import json

import pytest

from benchmarks.fantom_adapter import (DATA, METHODS, build_presence, evaluation_questions,
    inventory, predict, public_input, score_question, weighted_f1)


def example(departure=False):
    short=('A: Leaving now\nB: Target one\nC: Target two\nA: Back now' if departure
           else 'B: Target one\nC: Target two\nA: Hello')
    return {'set_id':'x','part_id':'x','conv_id':0,'joining_speaker':'A',
            'short_context':short,'full_context':'D: Earlier\n'+short+'\nD: Later',
            'factQA':{'question':'What happened?','correct_answer':'SECRET','wrong_answer':'OTHER'},
            'beliefQAs':[{'correct_answer':'SECRET'}],
            'infoAccessibilityQA_list':{'question':'List who knows.','correct_answer':['B','C'],'wrong_answer':['A','D']},
            'answerabilityQA_list':{'question':'List who answers.','correct_answer':['B','C'],'wrong_answer':['A','D']},
            'infoAccessibilityQAs_binary':[{'question':'Does D know this information?','correct_answer':'no:long'}],
            'answerabilityQAs_binary':[{'question':'Does A know the precise correct answer to this question?','correct_answer':'no'}]}


@pytest.mark.parametrize('departure',[False,True])
def test_gap_receipts_and_five_fixed_methods(departure):
    context=build_presence(example(departure))
    assert context['mapped']
    assert context['absence_rule']==('initial_departure_then_next_own_turn' if departure else 'first_turn_arrival')
    assert predict(context,METHODS[0],'full')['prediction']==['A','B','C','D']
    assert predict(context,METHODS[0],'short')['prediction']==['A','B','C']
    for method in METHODS[2:]:assert predict(context,method,'full')['prediction']==['B','C']
    assert predict(context,METHODS[0],'full')==predict(context,METHODS[1],'full')


def poison(value):
    if isinstance(value,list):return [poison(v) for v in value]
    if isinstance(value,dict):
        return {k:({'poison':'DO NOT INGEST'} if k in {'correct_answer','wrong_answer','missed_info','missed_info_accessibility','tom_type'} else poison(v)) for k,v in value.items()}
    return value


def test_all_public_gold_poison_leaves_contexts_receipts_unchanged():
    rows=json.loads(DATA.read_text())
    assert len(rows)==870
    for row in rows:
        poisoned=poison(deepcopy(row))
        assert public_input(row)==public_input(poisoned)
        assert build_presence(row)==build_presence(poisoned)


def test_official_inventory_and_non_gold_coverage():
    report=inventory(json.loads(DATA.read_text()))
    assert report['counts']['beliefQAs']==1540
    assert report['presence_mapping']['mapped_sets']==869
    assert report['presence_mapping']['warning_counts']=={'short_window_alignment_not_unique':1}


def test_bad_lines_and_ambiguous_alignment_not_silently_dropped():
    row=example();row['full_context']+='\n'+row['short_context']
    assert 'short_window_alignment_not_unique' in build_presence(row)['warnings']
    row=example();row['short_context']='unstructured\n'+row['short_context']
    assert 'unparsed_context_lines' in build_presence(row)['warnings']
    assert predict(build_presence(row),METHODS[-1],'short')['prediction'] is None


def test_no_long_exclusion_is_evaluation_only():
    row=example()
    context_before=build_presence(row)
    short=list(evaluation_questions(row,'short'));full=list(evaluation_questions(row,'full'))
    assert sum(not q['eligible'] for q in short)==1
    assert all(q['eligible'] for q in full)
    question=next(q for q in full if q['gold_answer']=='no:long')
    assert score_question(question,['B','C'])['correct']
    assert build_presence(row)==context_before


def test_list_criterion_and_weighted_f1_hand_computed():
    question=next(evaluation_questions(example(),'short'))
    assert score_question(question,['B','C'])['correct']
    assert not score_question(question,['A','B','C'])['correct']
    assert not score_question(question,['B'])['correct']
    rows=[{'gold_answer':'yes','predicted_answer':'yes'},
          {'gold_answer':'no','predicted_answer':'yes'},
          {'gold_answer':'no:long','predicted_answer':'no'}]
    assert weighted_f1(rows)==pytest.approx(2/3)
