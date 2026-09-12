"""Run actual HTTP protocol requests in both modern and legacy modes."""
import asyncio
import json
import sys
from mcp import Client


async def main():
    endpoint = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8001/mcp'
    for mode in ('auto', 'legacy'):
        async with Client(endpoint, mode=mode) as client:
            catalog = await client.list_tools()
            profiles = await client.call_tool('list_profiles', {})
            assert not profiles.is_error, profiles
            assert 'demo' in {p['id'] for p in profiles.structured_content['profiles']}
            result = await client.call_tool('search_knowledge', {'query': '', 'plane': 'fact', 'world': 'main', 'profile_id': 'demo'})
            assert not result.is_error, result
            assert result.structured_content['results'], 'Expected seeded fact assertions'
            assert all(a['plane'] == 'fact' for a in result.structured_content['results'])
            assert result.structured_content['profile_id'] == 'demo'
            print(json.dumps({'mode': mode, 'protocol': client.protocol_version,
                              'tools': [t.name for t in catalog.tools],
                              'fact_results': len(result.structured_content['results'])}))


asyncio.run(main())
