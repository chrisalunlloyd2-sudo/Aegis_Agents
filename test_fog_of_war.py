from fog_of_war import Fog, HexGrid, HexCell, TodoBoard


def test_populate_reveals_neighbours():
    g = HexGrid()
    g.populate(0, 0)
    assert g.fog_of(0, 0) == Fog.EXPLORED
    assert g.fog_of(1, 0) == Fog.VISIBLE
    assert len(g.frontier()) == 6


def test_frontier_grows():
    g = HexGrid()
    g.populate(0, 0)
    g.populate(1, 0)
    assert len(g.frontier()) == 8


def test_todo_priority_and_deps():
    b = TodoBoard()
    a = b.add("first", priority=1)
    b.add("second", priority=2)
    c = b.add("third", priority=1, deps=[a])
    assert b.next().title == "first"
    b.complete(a)
    assert b.next().title == "third"  # deps satisfied, higher priority
    b.complete(c)
    assert b.next().title == "second"


def test_cell_board():
    c = HexCell(0, 0)
    assert c.cell_id and c.key == (0, 0)
    c.board.add("x")
    assert c.board.stats()["total"] == 1
