import json

from hi.core import jsonl


def write(path, rows, mode="w"):
    with path.open(mode) as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_rows_are_read_in_order_and_a_missing_file_is_empty(tmp_path):
    assert jsonl.read(tmp_path / "nope.jsonl") == []
    path = tmp_path / "a.jsonl"
    write(path, [{"n": 1}, {"n": 2}])
    assert jsonl.read(path) == [{"n": 1}, {"n": 2}]


def test_an_unchanged_file_is_not_parsed_again(tmp_path, monkeypatch):
    path = tmp_path / "a.jsonl"
    write(path, [{"n": 1}])
    jsonl.read(path)
    parsed = []
    monkeypatch.setattr(jsonl.json, "loads", lambda line: parsed.append(line) or {"n": 0})
    jsonl.read(path), jsonl.read(path)
    assert parsed == []


def test_an_append_is_always_seen(tmp_path):
    path = tmp_path / "a.jsonl"
    write(path, [{"n": 1}])
    assert len(jsonl.read(path)) == 1
    write(path, [{"n": 2}], mode="a")
    assert [r["n"] for r in jsonl.read(path)] == [1, 2]


def test_a_rewrite_that_keeps_the_size_is_still_seen_because_the_time_changes(tmp_path):
    import os

    path = tmp_path / "a.jsonl"
    write(path, [{"n": 1}])
    jsonl.read(path)
    write(path, [{"n": 2}])  # same size
    os.utime(path, ns=(1, 2_000_000_000))
    assert jsonl.read(path) == [{"n": 2}]


def test_torn_and_non_object_lines_are_skipped(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text('{"n": 1}\n{"n": \n[1, 2]\n"text"\n{"n": 3}\n')
    assert [r["n"] for r in jsonl.read(path)] == [1, 3]


def test_the_cache_does_not_grow_without_limit(tmp_path):
    for i in range(jsonl.MAX_CACHED_FILES + 5):
        path = tmp_path / f"{i}.jsonl"
        write(path, [{"i": i}])
        jsonl.read(path)
    assert len(jsonl._cache) <= jsonl.MAX_CACHED_FILES


def test_different_paths_do_not_share_results(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write(a, [{"v": "a"}])
    write(b, [{"v": "b"}])
    assert jsonl.read(a)[0]["v"] == "a" and jsonl.read(b)[0]["v"] == "b"
