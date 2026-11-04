"""Drive the registered unit without computing or buffering hardware results."""


def run(env, transactions):
    """Offer one transaction, wait for the public response, and sample its pins."""

    env.drive(req_valid=0, resp_ready=1)
    for transaction in transactions:
        while env.cycle < transaction["release_cycle"]:
            env.tick()
        env.drive(**transaction["inputs"])
        env.drive(req_valid=1)
        while not env.read("req_ready"):
            env.tick()
        env.accept(transaction["id"])
        env.tick()
        env.drive(req_valid=0)
        while not env.read("resp_valid"):
            env.tick()
        env.sample(transaction["id"], {"result": "result"})
        env.tick()
