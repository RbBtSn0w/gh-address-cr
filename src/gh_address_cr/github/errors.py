from __future__ import annotations


class GitHubError(RuntimeError):
    def __init__(self, reason_code: str, detail: str, *, retryable: bool = False):
        self.reason_code = reason_code
        self.retryable = retryable
        super().__init__(detail)


class GitHubAuthError(GitHubError):
    def __init__(self, detail: str):
        super().__init__("GITHUB_AUTH_FAILED", detail, retryable=False)


class GitHubRateLimitError(GitHubError):
    def __init__(self, detail: str):
        super().__init__("GITHUB_RATE_LIMITED", detail, retryable=True)


class GitHubNotFoundError(GitHubError):
    def __init__(self, detail: str):
        super().__init__("GITHUB_NOT_FOUND", detail, retryable=False)


class GitHubTransientError(GitHubError):
    def __init__(self, detail: str):
        super().__init__("GITHUB_TRANSIENT_ERROR", detail, retryable=True)
