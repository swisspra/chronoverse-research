from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from chronoverse.api import create_app
from chronoverse.imports import ImportService, ImportLimitError
from chronoverse.models import AssertionInput, EventInput, QueryRequest
from chronoverse.profiles import ProfileManager


def claim(id="same", object="Ada", **extra):
    return dict(id=id, subject="Harbor", predicate="director", object=object, valid_from="2026-01-01", recorded_at="2026-01-01", evidence=[{"title":"Synthetic evidence","text":"Synthetic: Harbor director is " + object}], **extra)


@pytest.fixture
def manager(tmp_path):
    manager = ProfileManager(tmp_path / "demo.sqlite3")
    yield manager
    manager.close()


def make_pdf(text=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    if text:
        font = DictionaryObject({NameObject("/Type"):NameObject("/Font"), NameObject("/Subtype"):NameObject("/Type1"), NameObject("/BaseFont"):NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 150 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_profiles_isolate_ids_events_and_persist(tmp_path):
    manager = ProfileManager(tmp_path / "demo.sqlite3")
    a, b = manager.create_profile("Workspace A"), manager.create_profile("Workspace B")
    assert a["counts"] == {"assertions":0,"events":0}
    for profile, person in ((a,"Ada"),(b,"Bea")):
        manager.get_store(profile["id"]).add_assertion(AssertionInput(**claim(object=person)))
    manager.get_store(a["id"]).add_event("same", EventInput(type="retract", effective_at="2026-01-01", recorded_at="2026-02-01", reason="Synthetic withdrawal", source="Source"))
    assert manager.query(a["id"], QueryRequest(query="Harbor"))["results"] == []
    assert manager.query(b["id"], QueryRequest(query="Harbor"))["results"][0]["object"] == "Bea"
    assert manager.get_store(b["id"]).get_assertion("same")["events"] == []
    manager.close()
    restored = ProfileManager(tmp_path / "demo.sqlite3")
    assert {p["id"] for p in restored.list_profiles()} == {"demo",a["id"],b["id"]}
    assert restored.get_store(b["id"]).get_assertion("same")["object"] == "Bea"
    restored.close()


def test_profile_names_are_not_paths_and_unknown_ids_fail(manager):
    profile = manager.create_profile("../a name / still just a label")
    assert profile["id"].startswith("p-")
    with pytest.raises(ValueError, match="profile"):
        manager.get_store("../../outside")
    with pytest.raises(KeyError):
        manager.get_store("p-" + "0" * 32)
    with pytest.raises(ValueError, match="already exists"):
        manager.create_profile("../a name / still just a label")


def test_text_preview_commit_search_replay_and_profile_binding(manager):
    a, b = manager.create_profile("Docs A"), manager.create_profile("Docs B")
    service = ImportService(manager)
    data = "# Research\n\nChronoverse retains temporal evidence.\n\nQuantumacorn is a searchable marker.".encode()
    preview = service.preview(a["id"], "research.md", data)
    assert preview["assertion_count"] > 0
    assert manager.get_store(a["id"]).meta()["counts"]["assertions"] == 0
    with pytest.raises(KeyError):
        service.commit(b["id"], preview["preview_id"])
    result = service.commit(a["id"], preview["preview_id"])
    assert result["inserted_count"] == preview["assertion_count"]
    again = service.commit(a["id"], preview["preview_id"])
    assert again["inserted_count"] == 0
    assert again["existing_count"] == preview["assertion_count"]
    repreview = service.preview(a["id"], "renamed.md", data)
    assert service.commit(a["id"], repreview["preview_id"])["inserted_count"] == 0
    query = manager.query(a["id"], QueryRequest(query="Quantumacorn"))
    assert query["results"]
    row = query["results"][0]
    assert row["plane"] == "report" and row["predicate"] == "contains passage"
    assert "Quantumacorn" in row["evidence"][0]["text"]
    assert manager.query(b["id"], QueryRequest(query="Quantumacorn"))["results"] == []


def test_prepare_validates_every_row_before_writes_and_atomic_commit(manager):
    profile = manager.create_profile("Atomic")
    service = ImportService(manager)
    malformed = [claim("good"), {**claim("bad"),"valid_from":"not-a-date"}]
    with pytest.raises(ValueError, match="row 2"):
        service.preview(profile["id"], "bad.json", json.dumps(malformed).encode())
    assert manager.get_store(profile["id"]).meta()["counts"]["assertions"] == 0
    preview = service.preview(profile["id"], "valid.json", json.dumps([claim("first"),claim("collision")]).encode())
    manager.get_store(profile["id"]).add_assertion(AssertionInput(**claim("collision", object="Bea")))
    with pytest.raises(ValueError, match="already exists"):
        service.commit(profile["id"], preview["preview_id"])
    with pytest.raises(KeyError):
        manager.get_store(profile["id"]).get_assertion("first")
    assert manager.get_store(profile["id"]).meta()["counts"]["assertions"] == 1


def test_preview_persistence_and_identical_file_commit_concurrency(tmp_path):
    manager = ProfileManager(tmp_path / "demo.sqlite3")
    profile = manager.create_profile("Persistent import")
    preview = ImportService(manager).preview(profile["id"], "source.txt", b"Durable source note for testing.")
    manager.close()
    first, second = ProfileManager(tmp_path / "demo.sqlite3"), ProfileManager(tmp_path / "demo.sqlite3")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda m: ImportService(m).commit(profile["id"], preview["preview_id"]), (first,second)))
        assert sum(r["inserted_count"] for r in results) == preview["assertion_count"]
        assert first.get_store(profile["id"]).meta(known_at="2099-01-01")["counts"]["assertions"] == preview["assertion_count"]
    finally:
        first.close(); second.close()


def test_pdf_text_extraction_and_scanned_or_malformed_rejection(manager):
    profile = manager.create_profile("PDF corpus")
    service = ImportService(manager)
    preview = service.preview(profile["id"], "report.pdf", make_pdf("PDF source marker moonstone"))
    assert preview["assertion_count"] == 1
    assert "moonstone" in preview["sample_assertions"][0]["evidence"][0]["text"]
    assert "page 1" in preview["sample_assertions"][0]["evidence"][0]["title"]
    with pytest.raises(ValueError, match="OCR"):
        service.preview(profile["id"], "scan.pdf", make_pdf())
    with pytest.raises(ValueError, match="PDF"):
        service.preview(profile["id"], "broken.pdf", b"not a pdf")
    assert manager.get_store(profile["id"]).meta()["counts"]["assertions"] == 0


@pytest.mark.parametrize("name,data", [("source.txt",b"\xff\xfe"),("source.md",b"   "),("source.exe",b"payload"),("source.json",b"[]"),("source.jsonl",b'{"bad":true}\n')])
def test_invalid_files_rejected_without_writes(manager,name,data):
    profile = manager.create_profile("Invalid docs")
    with pytest.raises(ValueError):
        ImportService(manager).preview(profile["id"],name,data)
    assert manager.get_store(profile["id"]).meta()["counts"]["assertions"] == 0


def test_oversize_file_rejected(manager):
    with pytest.raises(ImportLimitError):
        ImportService(manager).preview("demo","large.txt",b"x"*(10*1024*1024+1))


def test_jsonl_csv_and_templates(manager):
    profile = manager.create_profile("Structured")
    service = ImportService(manager)
    for name,data in [("rows.jsonl",json.dumps(claim("jsonl-row")).encode()),("rows.csv",b"id,subject,predicate,object,valid_from,evidence_title,evidence_text\ncsv-row,Harbor,director,Bea,2026-01-01,Synthetic,Synthetic evidence\n")]:
        preview=service.preview(profile["id"],name,data)
        assert service.commit(profile["id"],preview["preview_id"])["inserted_count"] == 1


def test_api_profile_scoped_detail_event_and_import(tmp_path):
    with TestClient(create_app(tmp_path/"api.sqlite3",allowed_hosts=["testserver"])) as client:
        a = client.post("/api/profiles",json={"name":"Client A"}).json()
        b = client.post("/api/profiles",json={"name":"Client B"}).json()
        assert a["counts"]["assertions"] == 0
        for p,obj in ((a,"Ada"),(b,"Bea")):
            assert client.post("/api/assertions",params={"profile_id":p["id"]},json=claim(object=obj)).status_code == 201
        assert client.get("/api/assertions/same",params={"profile_id":b["id"]}).json()["object"] == "Bea"
        event=client.post("/api/assertions/same/events",params={"profile_id":a["id"]},json={"type":"retract","effective_at":"2026-01-01","recorded_at":"2026-02-01","reason":"Withdrawn","source":"Synthetic"})
        assert event.status_code == 201
        assert client.get("/api/assertions/same",params={"profile_id":b["id"]}).json()["events"] == []
        assert client.get("/api/meta",params={"profile_id":"p-"+"0"*32}).status_code == 404
        assert client.get("/api/meta",params={"profile_id":"../escape"}).status_code == 422
        preview=client.post("/api/imports/preview",params={"profile_id":a["id"]},files={"file":("source.txt",b"Browseruploadmarker is source evidence.","text/plain")})
        assert preview.status_code == 200, preview.text
        assert client.post("/api/imports/commit",params={"profile_id":b["id"]},json={"preview_id":preview.json()["preview_id"]}).status_code == 404
        commit=client.post("/api/imports/commit",params={"profile_id":a["id"]},json={"preview_id":preview.json()["preview_id"]})
        assert commit.status_code == 200
        result=client.post("/api/query",params={"profile_id":a["id"]},json={"query":"Browseruploadmarker"}).json()
        assert result["profile_id"] == a["id"] and result["results"]
        assert client.get("/api/imports/templates/json").status_code == 200
        assert client.get("/api/meta",params={"profile_id":a["id"]}).json()["examples"] == []
        assert client.post("/api/evaluate",params={"profile_id":a["id"]},json={}).json()["evaluation_profile_id"] == "demo"


def test_null_structured_id_is_stable_on_repeat_commit(manager):
    profile=manager.create_profile("Nullable IDs")
    preview=ImportService(manager).preview(profile["id"],"nullable.json",json.dumps(claim(id=None)).encode())
    assert preview["sample_assertions"][0]["id"] is not None
    first=ImportService(manager).commit(profile["id"],preview["preview_id"])
    again=ImportService(manager).commit(profile["id"],preview["preview_id"])
    assert first["assertion_ids"] == again["assertion_ids"]
    assert again["inserted_count"] == 0


def test_deeply_nested_json_returns_actionable_validation_error(manager):
    with pytest.raises(ValueError,match="nested|nesting"):
        ImportService(manager).preview("demo","nested.json",b"["*10000+b"0"+b"]"*10000)


def test_document_passages_have_distinct_graph_identity(manager):
    profile=manager.create_profile("Document links")
    service=ImportService(manager)
    for filename,data in (("alpha.txt",b"First unique source."),("beta.txt",b"Second distinct source.")):
        preview=service.preview(profile["id"],filename,data)
        service.commit(profile["id"],preview["preview_id"])
    result=manager.query(profile["id"],QueryRequest(query=""))
    assert len(result["graph"]["nodes"]) == 4


def test_expired_preview_refresh_preserves_original_prepared_timestamps(manager):
    profile=manager.create_profile("Expired previews")
    service=ImportService(manager)
    preview=service.preview(profile["id"],"source.txt",b"Retained timestamp and source evidence.")
    first=service.commit(profile["id"],preview["preview_id"])
    with manager._catalog:
        manager._catalog.execute("UPDATE previews SET created_at='2000-01-01T00:00:00Z' WHERE id=?",(preview["preview_id"],))
    with pytest.raises(ValueError,match="expired"):
        service.commit(profile["id"],preview["preview_id"])
    refreshed=service.preview(profile["id"],"source.txt",b"Retained timestamp and source evidence.")
    second=service.commit(profile["id"],refreshed["preview_id"])
    assert second["assertion_ids"] == first["assertion_ids"]
    assert second["inserted_count"] == 0
    assert refreshed["sample_assertions"][0]["recorded_at"] == preview["sample_assertions"][0]["recorded_at"]


def test_encrypted_pdf_rejected_and_partial_scan_warns(manager):
    writer=PdfWriter()
    writer.add_blank_page(width=100,height=100)
    writer.encrypt("password")
    encrypted=BytesIO()
    writer.write(encrypted)
    with pytest.raises(ValueError,match="Encrypted"):
        ImportService(manager).preview("demo","locked.pdf",encrypted.getvalue())
    writer=PdfWriter(clone_from=BytesIO(make_pdf("Readable first page")))
    writer.add_blank_page(width=100,height=100)
    mixed=BytesIO()
    writer.write(mixed)
    result=ImportService(manager).preview("demo","mixed.pdf",mixed.getvalue())
    assert any("1 pages" in warning and "OCR" in warning for warning in result["warnings"])


def test_oversized_http_body_rejected_before_ingest(tmp_path):
    with TestClient(create_app(tmp_path/"body.sqlite3",allowed_hosts=["testserver"])) as client:
        response=client.post("/api/imports/preview",content=b"notparsed",headers={"content-type":"multipart/form-data; boundary=ignored","content-length":str(12*1024*1024)})
        assert response.status_code == 413
        assert client.get("/api/meta").json()["counts"]["assertions"] == 16
