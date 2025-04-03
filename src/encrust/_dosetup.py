"""
A script to replace setuptools' `setup.py`, so we can invoke py2app directly.
"""

if __name__ == '__main__':
    import sys

    sys.path.append(".")
    sys.argv[0] = "encrust-setup.py"

    from encrust_setup import description  # type:ignore[import-not-found]
    from setuptools import setup  # type:ignore[import-untyped]

    setup(**description.setupOptions())
