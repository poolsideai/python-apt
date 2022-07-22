"""Common testing stuff"""

import apt_pkg

import os
import shutil
import sys
import tempfile
import unittest


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


class TestCase(unittest.TestCase):
    """Base class for python-apt unittests"""

    def setUp(self):
        super(TestCase, self).setUp()
        self.resetConfig()
        self.temp_dir = self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir)
        self.testdir = os.path.dirname(__file__)
        os.chdir(self.testdir)

    def resetConfig(self):
        apt_pkg.config.clear("")
        for key in apt_pkg.config.list():
            apt_pkg.config.clear(key)

        # Avoid loading any host config files
        os.unsetenv("APT_CONFIG")
        apt_pkg.config["Dir::Etc::main"] = "/dev/null"
        apt_pkg.config["Dir::Etc::parts"] = "/dev/null"

        apt_pkg.init_config()
        apt_pkg.init_system()

        # Restore default values
        apt_pkg.config["Dir::Etc::main"] = "apt.conf"
        apt_pkg.config["Dir::Etc::parts"] = "apt.conf.d"
