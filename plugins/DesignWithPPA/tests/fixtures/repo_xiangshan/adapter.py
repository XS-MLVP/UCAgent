"""Drive a combinational byte-reordering unit through public pins."""


def run(env, transactions):
    """Apply each released input and capture the physical output."""

    for transaction in transactions:
        while env.cycle < transaction["release_cycle"]:
            env.tick()
        env.drive(**transaction["inputs"])
        env.accept(transaction["id"])
        env.sample(transaction["id"], {"result": "result"})
        env.tick()
