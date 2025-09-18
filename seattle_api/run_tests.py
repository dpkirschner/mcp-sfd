#!/usr/bin/env python3
"""Test runner script for Seattle API service."""

import sys
import subprocess


def run_tests():
    """Run all tests using pytest."""
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest", 
            "tests/", 
            "-v", 
            "--tb=short"
        ], cwd=".", capture_output=False)
        
        return result.returncode == 0
    except Exception as e:
        print(f"Error running tests: {e}")
        return False


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)