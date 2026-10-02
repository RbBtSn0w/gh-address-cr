"""Spec 039 L4: efficiency reports say which runtime build produced them."""

from __future__ import annotations

import unittest

import gh_address_cr
from gh_address_cr.core.runtime_build import origin_from_direct_url, runtime_build


class RuntimeBuildTests(unittest.TestCase):
    def test_version_comes_from_the_package_not_install_metadata(self):
        # Editable installs keep the metadata version from install time (seen as 3.5.3
        # while the code was 3.16.0), so only __version__ is trustworthy.
        self.assertEqual(runtime_build()["version"], gh_address_cr.__version__)

    def test_origin_from_install_metadata(self):
        self.assertEqual(origin_from_direct_url(None), {"origin": "package", "commit": None})
        self.assertEqual(
            origin_from_direct_url({"url": "file:///private/path", "dir_info": {"editable": True}}),
            {"origin": "editable", "commit": None},
        )
        self.assertEqual(
            origin_from_direct_url(
                {"url": "file:///private/path", "vcs_info": {"vcs": "git", "commit_id": "d29455b4449abed8e868b5f1"}}
            ),
            {"origin": "vcs", "commit": "d29455b4449a"},
        )

    def test_build_never_carries_the_install_url(self):
        build = origin_from_direct_url({"url": "file:///Users/someone/private/repo", "dir_info": {"editable": True}})
        self.assertNotIn("/Users/", str(build))


if __name__ == "__main__":
    unittest.main()
