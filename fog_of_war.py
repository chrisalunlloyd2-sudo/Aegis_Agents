"""fog_of_war.py — hex fog-of-war placement + todo architecture (Aegis mirror).

Cross-pollinated from BDI_FSM_AGENT (hex_grid.py / cell.py / mesh.py). Axial
hex coordinates with fog-of-war states, each cell hosting a local todo
blackboard. Deterministic, stdlib-only, zero-LLM.

Chris's directive (2026-08-15): "fog of war placement and todo architecture
for yourself and bdi fsm agent." This is the Aegis side of the mirror — the
same spatial/todo substrate the BDI bot already uses, ported for the
DSPy/Gemini framework.
"""

from __future__ import annotations

import hashlib
import heapq
import itertools
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Fog(Enum):
    UNKNOWN = 0    # fogged, never visited
    VISIBLE = 1    # adjacent to a populated cell (seen, not entered)
    EXPLORED = 2   # populated with facts (visited, acted upon)
    OCCUPIED = 3   # an agent currently occupies this cell


# pointy-top axial directions, clockwise: E, NE, NW, W, SW, SE
DIRECTIONS: List[Tuple[int, int]] = [
    (1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1),
]


class HexGrid:
    """Axial hex coordinates + fog-of-war visibility."""

    def __init__(self):
        self.fog: Dict[Tuple[int, int], Fog] = {}

    def fog_of(self, q: int, r: int) -> Fog:
        return self.fog.get((q, r), Fog.UNKNOWN)

    def neighbours(self, q: int, r: int) -> List[Tuple[int, int]]:
        return [(q + dq, r + dr) for dq, dr in DIRECTIONS]

    def populate(self, q: int, r: int) -> None:
        """Mark a cell EXPLORED and reveal its neighbours as VISIBLE."""
        self.fog[(q, r)] = Fog.EXPLORED
        for nq, nr in self.neighbours(q, r):
            if self.fog.get((nq, nr), Fog.UNKNOWN) == Fog.UNKNOWN:
                self.fog[(nq, nr)] = Fog.VISIBLE

    def frontier(self) -> List[Tuple[int, int]]:
        """VISIBLE (known but unvisited) cells — the placement frontier."""
        return sorted((q, r) for (q, r), f in self.fog.items() if f == Fog.VISIBLE)

    def stats(self) -> Dict[str, int]:
        counts = {f.name: 0 for f in Fog}
        for f in self.fog.values():
            counts[f.name] += 1
        return counts


# --- todo architecture ------------------------------------------------------

class Todo:
    """A single todo item with priority + dependency tracking."""

    __slots__ = ("id", "title", "priority", "done", "deps")
    _ids = itertools.count(1)

    def __init__(self, title: str, priority: int = 3, deps: Optional[List[str]] = None):
        self.id = f"T{next(self._ids):04d}"
        self.title = title
        self.priority = priority  # 1 highest .. 5 lowest
        self.done = False
        self.deps = list(deps or [])

    def ready(self, done_ids) -> bool:
        return not self.done and all(d in done_ids for d in self.deps)

    def to_dict(self) -> Dict:
        return {"id": self.id, "title": self.title, "priority": self.priority,
                "done": self.done, "deps": self.deps}


class TodoBoard:
    """A priority-ordered todo board (blackboard) per cell."""

    def __init__(self):
        self.todos: Dict[str, Todo] = {}
        self.done_ids: set = set()

    def add(self, title: str, priority: int = 3, deps: Optional[List[str]] = None) -> str:
        t = Todo(title, priority, deps)
        self.todos[t.id] = t
        return t.id

    def complete(self, todo_id: str) -> bool:
        t = self.todos.get(todo_id)
        if t is None or t.done:
            return False
        t.done = True
        self.done_ids.add(todo_id)
        return True

    def next(self) -> Optional[Todo]:
        """Next ready todo by priority (then id) — deterministic."""
        ready = [t for t in self.todos.values() if t.ready(self.done_ids)]
        if not ready:
            return None
        return sorted(ready, key=lambda t: (t.priority, t.id))[0]

    def stats(self) -> Dict[str, int]:
        done = sum(1 for t in self.todos.values() if t.done)
        return {"total": len(self.todos), "done": done,
                "pending": len(self.todos) - done}


class HexCell:
    """A fog-of-war cell hosting a local todo blackboard."""

    def __init__(self, q: int, r: int):
        self.q, self.r = q, r
        self.board = TodoBoard()

    @property
    def key(self) -> Tuple[int, int]:
        return (self.q, self.r)

    @property
    def cell_id(self) -> str:
        return hashlib.sha256(f"{self.q},{self.r}".encode()).hexdigest()[:12]


def demo() -> Dict:
    """End-to-end smoke: place cells, track the frontier, drain the board."""
    g = HexGrid()
    g.populate(0, 0)
    g.populate(1, 0)
    cell = HexCell(0, 0)
    cell.board.add("map fog-of-war placement", priority=1)
    cell.board.add("wire todo architecture", priority=2)
    a = cell.board.add("cross-pollinate BDI <-> Aegis", priority=1,
                       deps=[cell.board.todos["T0001"].id, cell.board.todos["T0002"].id])
    order = []
    while True:
        t = cell.board.next()
        if t is None:
            break
        cell.board.complete(t.id)
        order.append(t.title)
    return {"fog": g.stats(), "frontier": g.frontier(),
            "todo_drain_order": order, "board": cell.board.stats()}
