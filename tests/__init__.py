import os
import sys


def get_library_dir():
    # Find the path to the built apt_pkg and apt_inst extensions
    builddir = os.path.join(
        os.path.abspath(os.path.dirname(__file__)), "../build")
    if not os.path.exists(builddir):
        return None
    from sysconfig import get_platform, get_python_version
    # Set the path to the build directory.
    plat_specifier = ".%s-%s" % (get_platform(), get_python_version())
    library_dir = "%s/lib%s%s" % (builddir, plat_specifier,
                                        (sys.pydebug and "-pydebug" or ""))
    return os.path.abspath(library_dir)


# Python 3 only provides abiflags since 3.2
if not hasattr(sys, "pydebug"):
    if sys.abiflags.startswith("d"):
        sys.pydebug = True
    else:
        sys.pydebug = False

assert "apt_pkg" not in sys.modules
assert "apt_inst" not in sys.modules

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
