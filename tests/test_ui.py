#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test cases for UI modules."""

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))


from ucagent.verify_ui import enter_simple_tui


def test_enter_simple_tui():
    """Test entering the simple TUI."""
    from ucagent.verify_pdb import VerifyPDB
    agent = None  # Replace with an actual agent instance if needed
    pdb = VerifyPDB(agent)
    
    # Call the function to enter the TUI
    enter_simple_tui(pdb)
    
    # If no exceptions are raised, the test passes
    assert True, "TUI entered successfully without exceptions."


if __name__ == "__main__":
    test_enter_simple_tui()
    print("Test passed: TUI entered successfully.")
