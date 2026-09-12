from copy import deepcopy
from benchmarks.sufficiency_v3 import calibrate,gate_row


def test_calibration_cannot_read_test_labels_or_outputs():
    row={'results':[{'id':'a','score_breakdown':{'vector':.8},'evidence':[],'events':[]}], 'gold_support':['assertion:a'],'found_support':['assertion:a'],'missing_support':[],'leaks':[]}
    result={'query_manifest':[{'id':'dev','split':'dev'},{'id':'test','split':'test'}], 'methods':{'m':{'per_query':{'dev':row,'test':None}}}}
    one=calibrate(result);other=deepcopy(result);other['methods']['m']['per_query']['test']={'poison':'cannot access'}
    assert one==calibrate(other)


def test_gating_preserves_order_and_retains_leak_failure_when_returned():
    row={'results':[{'id':'a','score_breakdown':{'vector':.4},'evidence':[],'events':[]},{'id':'b','score_breakdown':{'vector':.7},'evidence':[],'events':[]}], 'gold_support':['assertion:a'],'found_support':['assertion:a'],'missing_support':[],'leaks':[{'type':'assertion','id':'b'}]}
    out=gate_row(row,.5,1.)
    assert [r['id'] for r in out['results']]==['b'] and out['missing_support']==['assertion:a']
    assert out['leaks']==row['leaks'] and len(row['results'])==2
