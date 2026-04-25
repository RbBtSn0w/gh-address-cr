"""GitHub IO adapters owned by the deterministic runtime."""

from gh_address_cr.github.client import GitHubClient
from gh_address_cr.github.errors import GitHubError

__all__ = ["GitHubClient", "GitHubError"]
