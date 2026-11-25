"""Connect a TUI to an existing Agent without constructing a workflow."""
import argparse
from ucagent import DiskRunProvider, SuperAgentView

def attach(argv):
    parser = argparse.ArgumentParser(prog="ucagent attach", description=__doc__)
    parser.add_argument("session_dir")
    parser.add_argument("--agent", required=True)
    args = parser.parse_args(argv)
    provider = DiskRunProvider(args.session_dir)
    provider(args.agent)
    from ucagent import AttachApp
    AttachApp(SuperAgentView(provider, args.agent)).run()
