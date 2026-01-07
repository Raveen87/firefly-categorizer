import sys
import os
import pytest

# Add src to path so tests can import the package without installation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
