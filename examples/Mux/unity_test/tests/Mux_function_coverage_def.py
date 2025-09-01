
import toffee.funcov as fc

# Create coverage groups
funcov_select = fc.CovGroup("FG-SELECT")
funcov_api = fc.CovGroup("FG-API")

funcov_group = [funcov_select, funcov_api]

def init_coverage_groups(dut):
    # SELECT group
    funcov_select.add_watch_point(
        dut,
        {
            "CK-BASIC": lambda x: x.sel.value == 0 and x.in_data.value == 0b0001 and x.out.value == 1,
            "CK-ISOLATION": lambda x: x.sel.value == 0 and x.in_data.value == 0b1110 and x.out.value == 0,
        },
        name="FC-SELECT-0",
    )
    funcov_select.add_watch_point(
        dut,
        {
            "CK-BASIC": lambda x: x.sel.value == 1 and x.in_data.value == 0b0010 and x.out.value == 1,
            "CK-ISOLATION": lambda x: x.sel.value == 1 and x.in_data.value == 0b1101 and x.out.value == 0,
        },
        name="FC-SELECT-1",
    )
    funcov_select.add_watch_point(
        dut,
        {
            "CK-BASIC": lambda x: x.sel.value == 2 and x.in_data.value == 0b0100 and x.out.value == 1,
            "CK-ISOLATION": lambda x: x.sel.value == 2 and x.in_data.value == 0b1011 and x.out.value == 0,
        },
        name="FC-SELECT-2",
    )
    funcov_select.add_watch_point(
        dut,
        {
            "CK-BASIC": lambda x: x.sel.value == 3 and x.in_data.value == 0b1000 and x.out.value == 1,
            "CK-ISOLATION": lambda x: x.sel.value == 3 and x.in_data.value == 0b0111 and x.out.value == 0,
        },
        name="FC-SELECT-3",
    )

    # API group
    funcov_api.add_watch_point(
        dut,
        {
            "CK-SELECT-0": lambda x: x.sel.value == 0,
            "CK-SELECT-1": lambda x: x.sel.value == 1,
            "CK-SELECT-2": lambda x: x.sel.value == 2,
            "CK-SELECT-3": lambda x: x.sel.value == 3,
        },
        name="FC-OPERATION",
    )


def get_coverage_groups(dut):
    """
    Get the list of functional coverage groups.
    """
    init_coverage_groups(dut)
    return funcov_group
