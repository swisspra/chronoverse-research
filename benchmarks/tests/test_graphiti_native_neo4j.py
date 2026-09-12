from benchmarks.graphiti_native_neo4j import (
    ARCHIVE_SHA256,
    BOLT_PORT,
    HTTP_PORT,
    MARKER,
    config_block,
)


def test_config_is_loopback_only_and_has_bounded_memory():
    text = config_block()
    assert MARKER in text
    assert f'server.bolt.listen_address=127.0.0.1:{BOLT_PORT}' in text
    assert f'server.http.listen_address=127.0.0.1:{HTTP_PORT}' in text
    assert '0.0.0.0' not in text
    assert 'server.memory.heap.max_size=1g' in text
    assert 'server.memory.pagecache.size=512m' in text
    assert 'dbms.usage_report.enabled=false' in text


def test_archive_hash_is_frozen_sha256():
    assert len(ARCHIVE_SHA256) == 64
    assert set(ARCHIVE_SHA256) <= set('0123456789abcdef')
