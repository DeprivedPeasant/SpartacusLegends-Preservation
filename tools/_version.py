"""Single source of truth for the preservation server and release version.

Update the version here only.  `spartacus_server.py` imports it (so the built
executable and its startup banner stay in sync) and `packaging/build_release.ps1`
parses it for the package and ZIP names.
"""

__version__ = "0.3.10"
