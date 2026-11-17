"""``find_uncovered`` compares units by qualname, which is not unique."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from honeyguide.gitio import Repo  # noqa: E402
from honeyguide.refresh import find_uncovered  # noqa: E402
from test_core_fixtures import GitRepo  # noqa: E402

BEFORE = '''class C:
    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, v):
        self._x = v
'''
AFTER = BEFORE + '''

def added():
    return 1
'''


def test_unchanged_property_getter_is_not_reported_changed(tmp_path):
    """Getter and setter are both units 'C.x'; `before` keeps only the
    setter's hash, so the untouched getter is reported 'changed'."""
    g = GitRepo(tmp_path / "r")
    g.write("m.py", BEFORE)
    a = g.commit()
    g.write("m.py", AFTER)
    b = g.commit()
    uncovered, _ = find_uncovered(Repo.open(g.root), a, b, [])
    assert [(u.qualname, u.change) for u in uncovered] == [("added", "new")]
