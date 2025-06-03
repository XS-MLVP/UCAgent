

def test_fake_pass():
    """A fake test function to ensure the test framework is working."""
    assert True, "This is a fake test to ensure the test framework is working."


def test_fake_fail():
    """A fake test function that intentionally fails."""
    assert False, "This is a fake test that intentionally fails to demonstrate failure handling."


def test_add_normal():
    """A fake test function to simulate a normal addition operation."""
    assert 1 + 1 == 2, "Expected 1 + 1 to equal 2"


class TestA:
    def test_a(self):
        """A test method in class TestA."""
        assert True, "This is a test method in class TestA."
