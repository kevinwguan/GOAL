"""Allow python -m goal without installing the console script."""

from .cli import main

raise SystemExit(main())
