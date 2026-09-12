"""Protocol tests exercise the same persistent kernel through MCP, not mock tools."""
import asyncio
import pytest
from mcp import Client


def test_mcp_catalog_and_temporal_search(tmp_path):
    async def run():
        from chronoverse.mcp_server import create_server
        from chronoverse.store import Store
        store = Store(tmp_path / 'ledger.sqlite3', seed=True)
        try:
            server = create_server(store)
            for mode in ('auto', 'legacy'):
                async with Client(server, mode=mode) as client:
                    tools = await client.list_tools()
                    assert {t.name for t in tools.tools} == {
                        'search_knowledge', 'inspect_assertion', 'trace_entity',
                        'compare_snapshots', 'knowledge_schema', 'list_profiles',
                    }
                    assert all(t.annotations.read_only_hint for t in tools.tools)
                    result = await client.call_tool('search_knowledge', {'query': '', 'world': 'main', 'plane': 'fact'})
                    assert not result.is_error
                    payload = result.structured_content
                    assert payload['results']
                    assert all(a['plane'] == 'fact' and a['world'] == 'main' for a in payload['results'])
                    bad = await client.call_tool('search_knowledge', {'query': 'news', 'known_at': 'not-a-date'})
                    assert bad.is_error
        finally:
            store.close()
    asyncio.run(run())


def test_injected_store_rejects_unknown_profile(tmp_path):
    async def run():
        from chronoverse.mcp_server import create_server
        from chronoverse.store import Store
        store = Store(tmp_path / 'ledger.sqlite3')
        try:
            async with Client(create_server(store)) as client:
                result = await client.call_tool('search_knowledge', {'query': '', 'profile_id': 'missing'})
                assert result.is_error
                catalog = await client.call_tool('list_profiles', {})
                assert not catalog.is_error
                assert [p['id'] for p in catalog.structured_content['profiles']] == ['demo']
        finally:
            store.close()
    asyncio.run(run())


def test_mcp_profiles_isolate_search_detail_and_defaults(tmp_path):
    async def run():
        from chronoverse.mcp_server import create_server
        from chronoverse.profiles import ProfileManager
        from chronoverse.models import AssertionInput
        manager = ProfileManager(tmp_path / 'ledger.sqlite3')
        first = manager.create_profile('First')['id']
        second = manager.create_profile('Second')['id']
        try:
            for pid, value in ((first, 'Alpha'), (second, 'Beta')):
                manager.get_store(pid).add_assertion(AssertionInput(
                    id='shared-id', subject='Observatory', predicate='director', object=value,
                    valid_from='2026-09-12T00:00:00Z',
                    evidence=[{'title': 'Synthetic example', 'text': value, 'synthetic': True}],
                ))
            async with Client(create_server(profiles=manager)) as client:
                catalog = await client.call_tool('list_profiles', {})
                assert {p['id'] for p in catalog.structured_content['profiles']} == {'demo', first, second}
                for pid, value in ((first, 'Alpha'), (second, 'Beta')):
                    for tool, args in (
                        ('search_knowledge', {'query': ''}),
                        ('trace_entity', {'entity': ''}),
                        ('inspect_assertion', {'assertion_id': 'shared-id'}),
                        ('knowledge_schema', {}),
                    ):
                        response = await client.call_tool(tool, {**args, 'profile_id': pid})
                        assert not response.is_error, response
                        payload = response.structured_content
                        assert payload['profile_id'] == pid
                        if tool in ('search_knowledge', 'trace_entity'):
                            assert [r['object'] for r in payload['results']] == [value]
                        elif tool == 'inspect_assertion':
                            assert payload['object'] == value
                hidden = await client.call_tool('inspect_assertion', {'assertion_id': 'shared-id'})
                assert hidden.is_error
                comparison = await client.call_tool('compare_snapshots', {
                    'query': '', 'valid_at': '2026-09-12',
                    'before_known_at': '2000-01-01', 'after_known_at': '2099-01-01',
                    'profile_id': first,
                })
                assert not comparison.is_error
                diff = comparison.structured_content
                assert diff['profile_id'] == first
                assert diff['added_ids'] == ['shared-id']
                assert [r['object'] for r in diff['after']['results']] == ['Alpha']
                bad = await client.call_tool('search_knowledge', {'query': '', 'profile_id': '../ledger'})
                assert bad.is_error
        finally:
            manager.close()
    asyncio.run(run())


def test_mcp_inspect_respects_world_and_knowledge_cutoff(tmp_path):
    async def run():
        from chronoverse.mcp_server import create_server
        from chronoverse.store import Store
        from chronoverse.models import QueryRequest
        store = Store(tmp_path / 'ledger.sqlite3', seed=True)
        try:
            row = store.query(QueryRequest(query='', world='main'))['results'][0]
            async with Client(create_server(store)) as client:
                hidden = await client.call_tool('inspect_assertion', {'assertion_id': row['id'], 'world': 'private'})
                assert hidden.is_error
                early = await client.call_tool('inspect_assertion', {'assertion_id': row['id'], 'known_at': '1900-01-01'})
                assert early.is_error
        finally:
            store.close()
    asyncio.run(run())


def test_http_transport_rejects_untrusted_host_and_origin(tmp_path):
    async def run():
        import httpx
        from chronoverse.mcp_server import create_server, build_http_app
        from chronoverse.store import Store
        store = Store(tmp_path / 'ledger.sqlite3')
        server = create_server(store)
        app = build_http_app(server)
        try:
            async with server.session_manager.run():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost:8001') as client:
                    body = {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}}}
                    headers = {'Accept':'application/json, text/event-stream'}
                    good = await client.post('/mcp', json=body, headers=headers)
                    assert good.status_code == 200
                    host = await client.post('/mcp', json=body, headers={**headers,'Host':'evil.example'})
                    assert host.status_code in (400,403,421)
                    origin = await client.post('/mcp', json=body, headers={**headers,'Origin':'https://evil.example'})
                    assert origin.status_code in (400,403,421)
        finally:
            store.close()
    asyncio.run(run())
