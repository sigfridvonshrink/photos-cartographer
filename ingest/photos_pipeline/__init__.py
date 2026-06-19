"""photos_pipeline — safe digiKam/Immich photo ingestion + GPS/time calibration + merge.

The three phases (prep / geotag / merge) plus the shared utilities, packaged so they can be
shipped as self-contained zipapp executables. Each phase module exposes `main()`.
"""

__version__ = "0.1.0"
