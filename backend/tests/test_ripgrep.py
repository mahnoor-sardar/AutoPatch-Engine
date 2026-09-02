from app.services.ripgrep import SearchTimedOut, search_in_files, search_repo


def test_ripgrep_finds_pattern(tmp_path):
    sample = tmp_path / "app.py"
    sample.write_text("def boom():\n    raise ValueError('needle-token')\n")
    output = search_repo(str(tmp_path), "needle-token")
    assert "needle-token" in output
    assert "app.py" in output


def test_search_in_files_localizes_symbol():
    hits = search_in_files(
        {"src/math.py": "def calculate():\n    return 1\n"},
        "calculate",
    )
    assert hits
    assert hits[0][0] == "src/math.py"


def test_search_in_files_stops_at_max_hits():
    files = {
        "a.py": "\n".join(f"needle {i}" for i in range(20)),
        "b.py": "\n".join(f"needle {i}" for i in range(20, 80)),
    }
    hits = search_in_files(files, "needle", max_hits=5)
    assert len(hits) == 5
    assert hits[-1][0] == "a.py"


def test_search_in_files_deadline_stops_scan():
    import time

    files = {"slow.py": "x\n" * 10}
    try:
        search_in_files(files, "x", deadline=time.monotonic() - 1)
    except SearchTimedOut:
        return
    raise AssertionError("expected SearchTimedOut")


def test_search_in_files_truncates_long_lines():
    files = {"big.py": "keep-token " + ("Z" * 5000)}
    hits = search_in_files(files, "keep-token", max_line_chars=20)
    assert hits
    assert len(hits[0][2]) == 20
