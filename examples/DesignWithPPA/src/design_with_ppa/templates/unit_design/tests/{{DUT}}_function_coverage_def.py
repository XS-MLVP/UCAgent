"""FG/FC/CK functional coverage for {{DUT}}."""

from toffee.funcov import CovGroup


def get_coverage_groups(env):
    """Return coverage groups over the normalized backend-neutral environment."""

    group = CovGroup("FG-DESIGN")
    group.add_watch_point(
        env,
        {"CK-EXPECTED": lambda _env: False},
        name="FC-BEHAVIOR",
    )
    return [group]
