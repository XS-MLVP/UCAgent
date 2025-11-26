#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test cases for BashScriptChecker."""

import os
import sys
import tempfile
import stat

current_dir = os.path.dirname(os.path.abspath(__file__))
# Insert workspace path at the beginning to ensure we use local code
sys.path.insert(0, os.path.abspath(os.path.join(current_dir, "..")))

from ucagent.checkers import BashScriptChecker
from ucagent.util.functions import yam_str


def test_bash_script_success():
    """Test bash script execution with successful exit code."""
    print("\n=== Test: Bash Script Success ===")
    checker = BashScriptChecker(
        cmd="echo",
        arguments=["Hello World"]
    )
    passed, result = checker.do_check()
    print(f"Passed: {passed}")
    print(f"Result: {yam_str(result)}")
    assert passed is True, "Expected command to succeed"


def test_bash_script_failure():
    """Test bash script execution with failure exit code."""
    print("\n=== Test: Bash Script Failure ===")
    checker = BashScriptChecker(
        cmd="ls",
        arguments=["/nonexistent/path/that/does/not/exist"]
    )
    passed, result = checker.do_check()
    print(f"Passed: {passed}")
    print(f"Result: {yam_str(result)}")
    assert passed is False, "Expected command to fail"


def test_bash_script_pass_pattern():
    """Test bash script with pass pattern matching."""
    print("\n=== Test: Bash Script Pass Pattern ===")
    checker = BashScriptChecker(
        cmd="echo",
        arguments=["All tests passed successfully"],
        pass_pattern={
            "All tests passed": "Test suite completed successfully",
            "passed": "Tests passed"
        }
    )
    passed, result = checker.do_check()
    print(f"Passed: {passed}")
    print(f"Result: {yam_str(result)}")
    assert passed is True, "Expected pass pattern to match"
    assert "message" in result, "Expected message in result"


def test_bash_script_fail_pattern():
    """Test bash script with fail pattern matching."""
    print("\n=== Test: Bash Script Fail Pattern ===")
    checker = BashScriptChecker(
        cmd="echo",
        arguments=["Error: Something went wrong"],
        fail_pattern={
            "Error:": "Command encountered an error",
            "Failed": "Command failed"
        }
    )
    passed, result = checker.do_check()
    print(f"Passed: {passed}")
    print(f"Result: {yam_str(result)}")
    assert passed is False, "Expected fail pattern to match"
    assert "message" in result, "Expected message in result"


def test_bash_script_wildcard_pattern():
    """Test bash script with wildcard pattern matching."""
    print("\n=== Test: Bash Script Wildcard Pattern ===")
    checker = BashScriptChecker(
        cmd="echo",
        arguments=["Test result: 42 tests passed"],
        pass_pattern={
            "*tests passed*": "Tests passed with wildcard"
        }
    )
    passed, result = checker.do_check()
    print(f"Passed: {passed}")
    print(f"Result: {yam_str(result)}")
    assert passed is True, "Expected wildcard pattern to match"


def test_bash_script_regex_pattern():
    """Test bash script with regex pattern matching."""
    print("\n=== Test: Bash Script Regex Pattern ===")
    
    # Test with pass regex only
    checker = BashScriptChecker(
        cmd="echo",
        arguments=["Total: 100 tests, Passed: 98, Failed: 0"],
        pass_pattern={
            r"Passed:\s+\d+": "Regex matched passed tests"
        }
    )
    passed, result = checker.do_check()
    print(f"Test 1 - Passed: {passed}")
    print(f"Test 1 - Result: {yam_str(result)}")
    assert passed is True, "Expected pass pattern to match"
    
    # Test with both patterns - fail should take priority
    checker = BashScriptChecker(
        cmd="echo",
        arguments=["Total: 100 tests, Passed: 98, Failed: 2"],
        pass_pattern={
            r"Passed:\s+\d+": "Regex matched passed tests"
        },
        fail_pattern={
            r"Failed:\s+[1-9]\d*": "Regex matched failed tests (non-zero)"
        }
    )
    passed, result = checker.do_check()
    print(f"Test 2 - Passed: {passed}")
    print(f"Test 2 - Result: {yam_str(result)}")
    assert passed is False, "Expected fail pattern to match before pass pattern"


def test_bash_script_timeout():
    """Test bash script with timeout."""
    print("\n=== Test: Bash Script Timeout ===")
    checker = BashScriptChecker(
        cmd="sleep",
        arguments=["5"],
        timeout=1
    )
    passed, result = checker.do_check()
    print(f"Passed: {passed}")
    print(f"Result: {yam_str(result)}")
    assert passed is False, "Expected command to timeout"
    assert "timed out" in str(result).lower(), "Expected timeout message"


def test_bash_script_with_script_file():
    """Test bash script execution from a temporary script file."""
    print("\n=== Test: Bash Script File Execution ===")
    
    # Create a temporary script file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        script_path = f.name
        f.write("""#!/bin/bash
echo "Starting test..."
echo "Test 1: PASS"
echo "Test 2: PASS"
echo "All tests passed"
exit 0
""")
    
    try:
        # Make script executable
        os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IEXEC)
        
        checker = BashScriptChecker(
            cmd="bash",
            arguments=[script_path],
            pass_pattern={
                "All tests passed": "Script completed successfully"
            }
        )
        passed, result = checker.do_check()
        print(f"Passed: {passed}")
        print(f"Result: {yam_str(result)}")
        assert passed is True, "Expected script to succeed"
    finally:
        # Clean up
        if os.path.exists(script_path):
            os.unlink(script_path)


def test_bash_script_stderr_capture():
    """Test bash script stderr capture."""
    print("\n=== Test: Bash Script STDERR Capture ===")
    
    # Create a temporary script that writes to stderr
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        script_path = f.name
        f.write("""#!/bin/bash
echo "Standard output"
echo "Error message" >&2
exit 1
""")
    
    try:
        os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IEXEC)
        
        checker = BashScriptChecker(
            cmd="bash",
            arguments=[script_path],
            fail_pattern={
                "Error message": "Error detected in stderr"
            }
        )
        passed, result = checker.do_check()
        print(f"Passed: {passed}")
        print(f"Result: {yam_str(result)}")
        assert passed is False, "Expected script to fail"
        assert "STDERR" in result, "Expected STDERR in result"
        assert "Error message" in result["STDERR"], "Expected error message in STDERR"
    finally:
        if os.path.exists(script_path):
            os.unlink(script_path)


def test_bash_script_multiple_patterns():
    """Test bash script with multiple pass and fail patterns."""
    print("\n=== Test: Bash Script Multiple Patterns ===")
    checker = BashScriptChecker(
        cmd="echo",
        arguments=["Tests: 50 passed, 0 failed, 0 skipped"],
        pass_pattern={
            "passed": "Some tests passed",
            "0 failed": "No failures detected",
            "*50 passed*": "All 50 tests passed"
        },
        fail_pattern={
            "failed": "Some tests failed",
            "error": "Error occurred"
        }
    )
    passed, result = checker.do_check()
    print(f"Passed: {passed}")
    print(f"Result: {yam_str(result)}")
    # Fail pattern "failed" should match first (even though it says "0 failed")
    assert passed is False, "Expected fail pattern to be checked first"


def test_bash_script_pattern_priority():
    """Test that fail patterns are checked before pass patterns."""
    print("\n=== Test: Bash Script Pattern Priority ===")
    output = "Test completed: 10 passed, 2 failed"
    
    # Test 1: Fail pattern should take priority
    checker = BashScriptChecker(
        cmd="echo",
        arguments=[output],
        pass_pattern={"passed": "Tests passed"},
        fail_pattern={"failed": "Tests failed"}
    )
    passed, result = checker.do_check()
    print(f"Test 1 - Passed: {passed}")
    print(f"Test 1 - Result: {yam_str(result)}")
    assert passed is False, "Expected fail pattern to take priority"
    
    # Test 2: Without fail pattern, pass pattern should match
    checker = BashScriptChecker(
        cmd="echo",
        arguments=[output],
        pass_pattern={"passed": "Tests passed"}
    )
    passed, result = checker.do_check()
    print(f"Test 2 - Passed: {passed}")
    print(f"Test 2 - Result: {yam_str(result)}")
    assert passed is True, "Expected pass pattern to match"


def test_bash_script_human_check_needed():
    """Test bash script with human check needed flag."""
    print("\n=== Test: Bash Script Human Check Needed ===")
    checker = BashScriptChecker(
        cmd="echo",
        arguments=["Test output"],
        need_human_check=True
    )
    print(f"Human check needed: {checker.is_human_check_needed()}")
    assert checker.is_human_check_needed() is True, "Expected human check to be needed"
    
    passed, result = checker.do_check()
    print(f"Passed: {passed}")
    print(f"Result: {yam_str(result)}")


def test_pattern_search_methods():
    """Test pattern search helper methods."""
    print("\n=== Test: Pattern Search Methods ===")
    checker = BashScriptChecker(cmd="echo")
    
    # Test normal string
    assert checker.is_normal_str("simple text") is True
    assert checker.is_normal_str("text*with*wildcard") is False
    assert checker.is_normal_str(r"\d+") is False
    print("Normal string detection: PASS")
    
    # Test global string (wildcard)
    assert checker.is_global_str("*pattern*") is True
    assert checker.is_global_str("pattern?") is True
    assert checker.is_global_str("simple") is False
    print("Global string detection: PASS")
    
    # Test pattern_search
    assert checker.pattern_search("hello", "hello world") is True
    assert checker.pattern_search("*world*", "hello world") is True
    assert checker.pattern_search(r"\d+", "value is 42") is True
    assert checker.pattern_search(r"Failed:\s+[1-9]\d*", "Failed: 2") is True
    assert checker.pattern_search("notfound", "hello world") is False
    print("Pattern search: PASS")


if __name__ == "__main__":
    # Run all tests
    test_bash_script_success()
    test_bash_script_failure()
    test_bash_script_pass_pattern()
    test_bash_script_fail_pattern()
    test_bash_script_wildcard_pattern()
    test_bash_script_regex_pattern()
    test_bash_script_timeout()
    test_bash_script_with_script_file()
    test_bash_script_stderr_capture()
    test_bash_script_multiple_patterns()
    test_bash_script_pattern_priority()
    test_bash_script_human_check_needed()
    test_pattern_search_methods()
    
    print("\n" + "="*50)
    print("All tests completed!")
    print("="*50)
