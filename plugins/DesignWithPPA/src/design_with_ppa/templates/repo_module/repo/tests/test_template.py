"""One public-pin test case; derive expected values from the frozen reference.

Replace this file, keep the pattern, and annotate covered FG/FC/CK paths::

    COVERS = ["FG-.../FC-.../CK-..."]

    def test_rotate(env, reference):
        transaction = {"id": "t1", "inputs": {"a": 255}}
        expected = reference([transaction])["t1"]["result"]
        env.drive(a=255)
        assert env.read("y") == expected
        env.tick()
"""

COVERS = []

def test_template(env):
    """Replace with a real public-pin assertion for one annotated checkpoint."""

    assert False, "Not implemented"
