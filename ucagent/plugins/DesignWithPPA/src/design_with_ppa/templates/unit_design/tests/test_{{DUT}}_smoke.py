"""Executable-spec smoke tests that run before detailed CK authoring."""

import pytest

from {{DUT}}_api import api_{{DUT}}_transaction


def test_{{DUT}}_smoke_reset(env):
    """Verify one observable reset-state output from the architecture contract."""

    assert False, "Not implemented"


def test_{{DUT}}_smoke_transaction(env):
    """Verify non-default data against an independent non-default exact result."""

    assert False, "Not implemented"


def test_{{DUT}}_smoke_invalid(env):
    """Verify one invalid public API request is rejected before DUT activity."""

    with pytest.raises((TypeError, ValueError)):
        api_{{DUT}}_transaction(env, None, max_cycles=0)
    assert False, "Not implemented"
