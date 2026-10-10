"""Keep the suite hermetic: never call a real language model unless a test opts in."""

import os

os.environ.setdefault("GREENIQ_LLM", "off")
