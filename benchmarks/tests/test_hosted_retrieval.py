import pytest
from benchmarks.hosted_retrieval import HostedEmbeddings,validate_response


def test_embedding_indices_and_shape():
    rows={'data':[{'index':0,'embedding':[1.]*3072},{'index':1,'embedding':[2.]*3072}]}
    assert validate_response(rows,2).shape==(2,3072)
    with pytest.raises(ValueError):validate_response(rows,1)
    with pytest.raises(ValueError):validate_response({'data':[{'index':0,'embedding':[0.]*3072}]},1)


def test_refuses_url_credentials(tmp_path):
    with pytest.raises(ValueError):HostedEmbeddings('http://user:password@localhost','key',tmp_path,100)


def test_budget_before_dispatch_and_exact_cache_reuse(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    tiktoken=SimpleNamespace(get_encoding=None)
    monkeypatch.setitem(sys.modules,'tiktoken',tiktoken)
    class Tokens:
        def encode(self,text,**kwargs):return list(text.encode())
        def decode(self,tokens):return bytes(tokens).decode()
    monkeypatch.setattr(tiktoken,'get_encoding',lambda _:Tokens())
    calls=[]
    def send(*args):
        calls.append(args)
        return {'data':[{'index':0,'embedding':[1.]*3072}],'usage':{'total_tokens':1},'model':'text-embedding-3-large'}
    tight=HostedEmbeddings('https://example.test/v1','secret',tmp_path/'tight',513,send)
    with pytest.raises(RuntimeError,match='cap'):tight.encode(['hello'])
    assert calls==[]
    client=HostedEmbeddings('https://example.test/v1','secret',tmp_path/'good',2000,send)
    first,_=client.encode(['hello']);second,_=client.encode(['hello'])
    assert len(calls)==1
    assert (first==second).all()


def test_uncertain_dispatch_is_never_implicitly_retried(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    tiktoken=SimpleNamespace(get_encoding=None)
    monkeypatch.setitem(sys.modules,'tiktoken',tiktoken)
    class Tokens:
        def encode(self,text,**kwargs):return [1]
        def decode(self,tokens):return 'x'
    monkeypatch.setattr(tiktoken,'get_encoding',lambda _:Tokens())
    calls=[]
    def fail(*args):calls.append(1);raise TimeoutError()
    client=HostedEmbeddings('https://example.test/v1','secret',tmp_path,2000,fail)
    with pytest.raises(TimeoutError):client.encode(['x'])
    with pytest.raises(RuntimeError,match='unresolved'):client.encode(['x'])
    assert len(calls)==1 and client.state['reserved_tokens']>0


def test_empty_input_is_not_sent_and_keeps_its_position(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules,'tiktoken',SimpleNamespace(get_encoding=lambda _:SimpleNamespace(encode=lambda s,**k:list(s.encode()),decode=lambda t:bytes(t).decode())))
    calls=[]
    def send(base,key,body):
        calls.append(body['input']);return {'data':[{'index':0,'embedding':[1.]*3072}],'usage':{'total_tokens':1},'model':body['model']}
    client=HostedEmbeddings('https://example.test/v1','secret',tmp_path,2000,send)
    vectors,meta=client.encode(['','hello'])
    assert calls==[['hello']] and meta['empty_inputs_excluded']==1
    assert not vectors[0].any() and vectors[1].any()


@pytest.mark.parametrize('recovery_succeeds',[True,False])
def test_explicit_timeout_recovery_keeps_prior_reservation_and_cannot_repeat(tmp_path,monkeypatch,recovery_succeeds):
    import sys
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules,'tiktoken',SimpleNamespace(get_encoding=lambda _:SimpleNamespace(encode=lambda s,**k:[1],decode=lambda t:'x')))
    calls=[]
    def send(base,key,body):
        calls.append(1)
        if len(calls)==1 or not recovery_succeeds:raise TimeoutError()
        return {'data':[{'index':0,'embedding':[1.]*3072}],'usage':{'total_tokens':1},'model':body['model']}
    first=HostedEmbeddings('https://example.test/v1','secret',tmp_path,2000,send)
    with pytest.raises(TimeoutError):first.encode(['x'])
    signature=next(iter(first.state['calls']));prior=first.state['reserved_tokens'];first.lock.close()
    second=HostedEmbeddings('https://example.test/v1','secret',tmp_path,2000,send,retry_timeout_signature=signature)
    if recovery_succeeds:
        second.encode(['x']);second.encode(['x'])
    else:
        with pytest.raises(TimeoutError):second.encode(['x'])
        with pytest.raises(RuntimeError,match='unresolved'):second.encode(['x'])
    assert len(calls)==2 and second.state['reserved_tokens']==2*prior
    record=second.state['calls'][signature]
    assert record['prior_attempts'][0]['status']=='failed_or_uncertain'
    assert record['reserved_tokens']==record['current_reservation']+prior
    second.lock.close()
    with pytest.raises(ValueError,match='one recorded timeout'):
        HostedEmbeddings('https://example.test/v1','secret',tmp_path,3000,send,retry_timeout_signature=signature)
