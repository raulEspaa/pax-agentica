"""Smoke test: the package imports. The first real test is yours (specs/001-...)."""

import pax_agentica


def test_package_has_a_version() -> None:
    assert pax_agentica.__version__ == "0.1.0"
