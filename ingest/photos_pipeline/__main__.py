"""`python -m photos_pipeline …` / the zipapp entry → the combined photos-ingest CLI."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
