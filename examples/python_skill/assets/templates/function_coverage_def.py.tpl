import toffee.funcov as fc


def get_coverage_groups(dut):
    group = fc.CovGroup("FG-PLACEHOLDER")
    group.add_watch_point(
        dut,
        {
            "CK-PLACEHOLDER": lambda _: True,
        },
        name="FC-PLACEHOLDER",
    )
    return [group]
