import json
from pathlib import Path

import pytest

from benchmarks import strong_lexical as lexical


def test_index_command_freezes_multifield_analyzer_configuration(tmp_path):
    command = lexical.index_command(tmp_path / "collection", tmp_path / "index")
    assert command[:3] == [lexical.sys.executable, "-m", "pyserini.index.lucene"]
    assert command[command.index("--generator") + 1] == "DefaultLuceneDocumentGenerator"
    assert command[command.index("--fields") + 1] == "title"
    assert command[command.index("--threads") + 1] == "1"
    assert "--pretokenized" not in command
    recorded = lexical.display_command(command)
    assert recorded[0] == "python"
    assert str(tmp_path) not in " ".join(recorded)


def test_prepare_collection_counts_empty_rows_without_dropping_input(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    corpus = source / "corpus.jsonl"
    queries = source / "queries.jsonl"
    qrels = source / "test.tsv"
    corpus.write_text(
        json.dumps({"_id": "d1", "title": "", "text": ""}) + "\n"
        + json.dumps({"_id": "d2", "title": "Title", "text": "Body"}) + "\n"
    )
    queries.write_text(json.dumps({"_id": "q1", "text": "query"}) + "\n")
    qrels.write_text("query-id\tcorpus-id\tscore\nq1\td2\t1\n")
    monkeypatch.setitem(lexical.DATASETS, "fixture", (2, 1))
    monkeypatch.setattr(lexical, "dataset_paths", lambda _: (corpus, queries, qrels))
    collection, loaded_queries, qids, empty = lexical.prepare_collection("fixture", tmp_path / "out")
    rows = [json.loads(line) for line in (collection / "documents.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert empty == 1
    assert loaded_queries == {"q1": "query"}
    assert qids == ["q1"]
    assert lexical.FIELD_WEIGHTS == {"contents": 1.0, "title": 1.0}
    assert (lexical.BM25_K1, lexical.BM25_B) == (0.9, 0.4)


def test_prepare_collection_keeps_title_and_contents_separate(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.jsonl"
    queries = tmp_path / "queries.jsonl"
    qrels = tmp_path / "test.tsv"
    corpus.write_text(json.dumps({"_id": "d1", "title": "T", "text": "Body"}) + "\n")
    queries.write_text(json.dumps({"_id": "q1", "text": "question"}) + "\n")
    qrels.write_text("query-id\tcorpus-id\tscore\nq1\td1\t1\n")
    monkeypatch.setattr(lexical, "dataset_paths", lambda _name: (corpus, queries, qrels))
    monkeypatch.setitem(lexical.DATASETS, "tiny", (1, 1))

    collection, selected, qids, empty = lexical.prepare_collection("tiny", tmp_path / "out")

    row = json.loads((collection / "documents.jsonl").read_text())
    assert row == {"id": "d1", "contents": "Body", "title": "T"}
    assert selected == {"q1": "question"}
    assert qids == ["q1"]
    assert empty == 0


def test_qrels_grades_are_not_returned(tmp_path):
    qrels = tmp_path / "qrels.tsv"
    qrels.write_text("query-id\tcorpus-id\tscore\nq2\td9\t2\nq1\td8\t1\nq2\td7\t99\n")
    assert lexical.test_query_ids(qrels) == ["q1", "q2"]


def test_validate_rankings_rejects_self_and_duplicates():
    lexical.validate_rankings({"q1": ["d1", "d2"]}, ["q1"])
    with pytest.raises(ValueError, match="self document"):
        lexical.validate_rankings({"q1": ["q1"]}, ["q1"])
    with pytest.raises(ValueError, match="duplicate"):
        lexical.validate_rankings({"q1": ["d1", "d1"]}, ["q1"])
