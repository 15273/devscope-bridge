from devscope_bridge import task_homes


def test_memory_roundtrip(tmp_path):
    task_homes.set_base_dir(tmp_path)
    try:
        assert task_homes.read_memory(7) == ""
        task_homes.write_memory(7, "# זיכרון\n- האתר איטי בבקרים\n")
        assert "האתר איטי" in task_homes.read_memory(7)
        task_homes.append_memory(7, "צריך להתחבר מחדש כל שבוע")
        assert "להתחבר מחדש" in task_homes.read_memory(7)
    finally:
        task_homes.set_base_dir(None)


def test_reports_listing(tmp_path):
    task_homes.set_base_dir(tmp_path)
    try:
        rd = task_homes.reports_dir(7)
        (rd / "daily.md").write_text("x", "utf-8")
        reports = task_homes.list_reports(7)
        assert reports[0]["name"] == "daily.md" and reports[0]["size"] == 1
    finally:
        task_homes.set_base_dir(None)
