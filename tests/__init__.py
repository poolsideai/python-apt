import os
import sys

from tests.testcommon import get_library_dir


# Python 3 only provides abiflags since 3.2
if not hasattr(sys, "pydebug"):
    if sys.abiflags.startswith("d"):
        sys.pydebug = True
    else:
        sys.pydebug = False


if not os.access("/etc/apt/sources.list", os.R_OK):
    sys.stdout.write(
        "[tests] Skipping because sources.list is not readable\n")
    sys.exit(0)

sys.stdout.write("[tests] Running on %s\n" % sys.version.replace("\n", ""))
dirname = os.path.abspath(os.path.dirname(__file__))
library_dir = get_library_dir()
if "pybuild" in os.getenv("PYTHONPATH", ""):
    # pybuild already supplied us with a path to check for
    sys.stdout.write("Using pybuild supplied build dir\n")
elif library_dir:
    sys.stdout.write("Using library_dir: '%s'\n" % library_dir)
    sys.path.insert(0, os.path.abspath(library_dir))
