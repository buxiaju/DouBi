"""Entry point for ``python -m doubi.ui``."""

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
