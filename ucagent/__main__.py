"""Launch UCAgent with python -m ucagent or an explicit package entry file."""

import os
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ucagent.application.entry import main

if __name__ == "__main__":
    main()
