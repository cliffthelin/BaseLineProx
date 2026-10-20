

def test_the_systems_you_can_create_are_drawn_even_before_the_first_machine_exists():
    import launcher_page
    page = launcher_page.render({"host": "h", "tiles": [], "apps": [], "schema": {"os": {}, "app": {}}, "available": []}).decode()
    empty_branch = page[page.index("if (!S.tiles.length)"):page.index("const grid = el('ul'")]
    assert "drawAvailable(home)" in empty_branch and "No virtual machines yet" in empty_branch
