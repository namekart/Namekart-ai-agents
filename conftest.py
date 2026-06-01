"""
Pytest configuration — adds the project root to sys.path so that
`agents`, `app`, `schemas` etc. are importable without installing the package.
"""
import sys
import os

# Insert project root at the front of sys.path
sys.path.insert(0, os.path.dirname(__file__))
