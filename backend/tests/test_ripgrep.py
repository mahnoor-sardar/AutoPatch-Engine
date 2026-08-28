from app.services.ripgrep import search_in_files, search_repo


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
