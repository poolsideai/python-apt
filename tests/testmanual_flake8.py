import os
import subprocess
import unittest


class PackageFlake8TestCase(unittest.TestCase):

    def test_flake8(self):
        res = 0
        py_dir = os.path.join(os.path.dirname(__file__), "..")
        res += subprocess.call(["flake8", py_dir])
        if res != 0:
            self.fail("flake8 failed with: %s" % res)


if __name__ == "__main__":
    unittest.main()
