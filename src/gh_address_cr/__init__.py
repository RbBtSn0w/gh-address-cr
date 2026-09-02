"""Deterministic runtime package for the gh-address-cr control plane."""

__version__ = "3.12.1"
# 1.1 moves reviewer-authored item text behind `item.untrusted_content`; 1.0 requests
# (flat `item.body`) stay readable so an in-flight lease survives the upgrade.
PROTOCOL_VERSION = "1.1"
SUPPORTED_PROTOCOL_VERSIONS = ("1.0", "1.1")
SUPPORTED_SKILL_CONTRACT_VERSIONS = ("1.0",)
MAX_PARALLEL_CLAIMS = 2
