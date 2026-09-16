"""Byte-list model independent of Scala and emitted hardware."""


def evaluate(transactions):
    """Rotate byte lanes in either direction, preserving every bit."""

    results = {}
    for transaction in transactions:
        inputs = transaction["inputs"]
        lanes = [(inputs["data"] >> (8 * index)) & 255 for index in range(8)]
        amount = inputs["amount"]
        if amount:
            lanes = (lanes[amount:] + lanes[:amount] if inputs["left"]
                     else lanes[-amount:] + lanes[:-amount])
        results[transaction["id"]] = {"result": sum(value << (8 * index) for index, value in enumerate(lanes))}
    return results
