from fastapi.testclient import TestClient

from chronoverse.api import create_app


def test_health_query_and_validation(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite3", allowed_hosts=["testserver"])) as client:
        assert client.get("/health").json() == {"status":"ok"}
        assert client.get("/api/meta").json()["counts"]["assertions"] >= 10
        response = client.post("/api/query", json={"query":"Harbor"})
        assert response.status_code == 200
        assert "graph" in response.json()
        assert client.post("/api/query", json={"known_at":"banana"}).status_code == 422
        assert client.get("/api/assertions/missing").status_code == 404
        assert client.get("/api/assertions?limit=999999").status_code == 422
        assert client.post("/api/assertions", json={}).status_code == 422
        assert client.post("/api/evaluate", json={}).json()["summary"]["chronoverse_passed"] > 0


def test_ingest_raw_evidence_and_lifecycle(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite3", allowed_hosts=["testserver"])) as client:
        data = dict(id="user-entry", subject="Test", predicate="has", object="evidence", valid_from="2026-01-01", recorded_at="2026-01-01", evidence=[dict(title="User note", text="Raw source text")])
        result = client.post("/api/assertions", json=data)
        assert result.status_code == 201
        assert result.json()["evidence"][0]["text"] == "Raw source text"
        assert client.post("/api/assertions", json=data).status_code == 201
        assert client.post("/api/assertions", json={**data,"object":"different"}).status_code == 409
        assert client.post("/api/assertions/user-entry/events", json={"type":"retract","effective_at":"2026-01-01","recorded_at":"2026-02-01","reason":"Withdrawn","source":"User source"}).status_code == 201
        assert client.get("/api/assertions/user-entry").json()["status"] == "retracted"


def test_static_directory_can_be_configured_for_installed_package(tmp_path, monkeypatch):
    static = tmp_path / "web"
    static.mkdir()
    (static / "index.html").write_text("<h1>Chronoverse test workbench</h1>")
    monkeypatch.setenv("CHRONOVERSE_STATIC_DIR", str(static))
    with TestClient(create_app(tmp_path / "static.sqlite3", allowed_hosts=["testserver"])) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Chronoverse test workbench" in response.text


def test_untrusted_hosts_rejected_while_local_hosts_work(tmp_path):
    with TestClient(create_app(tmp_path / "hosts.sqlite3"), base_url="http://127.0.0.1:8000") as client:
        assert client.get("/health").status_code == 200
        for host in ("localhost:8000", "127.0.0.1:8000", "[::1]:8000"):
            assert client.get("/api/meta", headers={"host":host}).status_code == 200
        for host in ("attacker.example:8000", "localhost.attacker.example", "testserver", "[::1].attacker.example", "[2001:db8::1]:8000"):
            assert client.get("/api/meta", headers={"host":host}).status_code == 400
            assert client.post("/api/assertions", headers={"host":host}, json={}).status_code == 400


def test_hosts_can_be_explicitly_configured_for_tests(tmp_path):
    with TestClient(create_app(tmp_path / "custom-hosts.sqlite3", allowed_hosts=["testserver"])) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health", headers={"host":"other.example"}).status_code == 400
