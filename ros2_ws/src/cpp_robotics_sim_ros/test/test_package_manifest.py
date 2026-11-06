#!/usr/bin/env python3
# Copyright 2026 Devansh Mishra
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""Validate the package manifest without fetching a remote schema."""

from pathlib import Path

from catkin_pkg.package import parse_package


def test_package_manifest_uses_valid_format_three_metadata():
    manifest = Path(__file__).resolve().parents[1] / 'package.xml'
    package = parse_package(str(manifest))

    assert package.package_format == 3
    assert package.name == 'cpp_robotics_sim_ros'
