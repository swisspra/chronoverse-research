from copy import deepcopy
from benchmarks.longmemeval_preflight import public_history


def test_ingress_discards_gold_and_turn_answer_flags():
    row={'question_id':'q','question':'what','question_date':'2020','answer':'secret','answer_session_ids':['s'],
         'haystack_session_ids':['s'],'haystack_dates':['2019'],'haystack_sessions':[[{'role':'user','content':'hello','has_answer':True}]]}
    altered=deepcopy(row);altered['answer']='poison';altered['answer_session_ids']=[];altered['haystack_sessions'][0][0]['has_answer']=False
    assert public_history(row)==public_history(altered)
    assert public_history(row)['sessions'][0]['turns']==[{'role':'user','content':'hello'}]
