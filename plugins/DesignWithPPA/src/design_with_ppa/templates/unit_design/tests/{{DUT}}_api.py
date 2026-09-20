"""Backend-neutral transaction API for {{DUT}}."""


def api_{{DUT}}_transaction(env, inputs, max_cycles=16):
    """Execute one specified transaction.

    Args:
        env: Active Python or RTL backend adapter.
        inputs: Transaction inputs defined by the architecture contract.
        max_cycles: Positive simulation-cycle timeout.

    Returns:
        The transaction result in the shared backend-neutral representation.
    """

    raise NotImplementedError("Implement through the shared adapter")
