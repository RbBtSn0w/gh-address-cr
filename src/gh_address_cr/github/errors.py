from __future__ import annotations

from typing import Any


class GitHubError(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        detail: str,
        *,
        retryable: bool = False,
        diagnostics: dict[str, Any] | None = None,
    ):
        self.reason_code = reason_code
        self.retryable = retryable
        self.diagnostics = diagnostics or {}
        super().__init__(detail)


class GitHubAuthError(GitHubError):
    def __init__(self, detail: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__("GITHUB_AUTH_FAILED", detail, retryable=False, diagnostics=diagnostics)


class GitHubNetworkError(GitHubError):
    def __init__(self, detail: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__("GITHUB_NETWORK_FAILED", detail, retryable=True, diagnostics=diagnostics)


class GitHubEnvironmentError(GitHubError):
    def __init__(self, detail: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__("GITHUB_ENVIRONMENT_FAILED", detail, retryable=False, diagnostics=diagnostics)


class GitHubRateLimitError(GitHubError):
    def __init__(self, detail: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__("GITHUB_RATE_LIMITED", detail, retryable=True, diagnostics=diagnostics)


class GitHubNoChecksError(GitHubError):
    """The pull request has no check runs: a PR state, not an API failure.

    Still a GitHubError, so `final-gate --require-checks` keeps blocking on it.
    """

    def __init__(self, detail: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__("GITHUB_PR_HAS_NO_CHECKS", detail, retryable=False, diagnostics=diagnostics)


class GitHubNotFoundError(GitHubError):
    def __init__(self, detail: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__("GITHUB_NOT_FOUND", detail, retryable=False, diagnostics=diagnostics)


class GitHubTransientError(GitHubError):
    def __init__(self, detail: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__("GITHUB_TRANSIENT_ERROR", detail, retryable=True, diagnostics=diagnostics)
