from benchmarks.scaled_delivery_fixture import build, encoded


def test_deterministic_shape_and_split_separation():
    data=build()
    assert encoded(data)==encoded(build())
    assert data['split_counts']['test']==500
    assert len(data['assertions'])>=5000 and len(data['events'])>=300 and len(data['receipts'])>=10000
    test=[q for q in data['queries'] if q['split']=='test'];dev=[q for q in data['queries'] if q['split']=='dev']
    assert not ({q['entity'] for q in test}&{q['entity'] for q in dev})
    assert not ({q['scenario_family'] for q in test}&{q['scenario_family'] for q in dev})
    assert len({(q['recipient_id'],q['query'],str(q['scope'])) for q in test})==500
    assert len({q['scenario_family'] for q in test})>=12
    assert {q['family'] for q in test}=={q['family'] for q in dev} # disclosed mechanism overlap


def test_time_only_versions_have_identical_text_and_compatibility_is_retained():
    data=build();rows={a['id']:a for a in data['assertions']}
    for q in data['queries']:
        if q['family']=='time_only_near_duplicate':
            a,b=rows[q['id']+'-a'],rows[q['id']+'-b']
            assert (a['subject'],a['predicate'],a['object'],a['summary'],a['evidence'][0]['text'])==(b['subject'],b['predicate'],b['object'],b['summary'],b['evidence'][0]['text'])
            assert a['valid_to']==b['valid_from']
    assert {'oq10','oq16','oq18','oq14','oq48','oq43'} <= {q['id'] for q in data['queries'] if q['split']=='compatibility'}
