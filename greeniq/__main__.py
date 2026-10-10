"""``python -m greeniq <command>``: same as the ``greeniq`` script, but works even where
the editable install's .pth file is skipped (seen on macOS when it gets the hidden flag)."""

import sys

from .cli import main

sys.exit(main())
