# GitHub Client Contract

The `src/gh_address_cr/github/` package manages all communication with GitHub.

## API Methods

### `list_threads(repo: str, pr_number: str) -> list[dict]`
- **Input**: Repository (owner/repo), PR number.
- **Output**: List of raw thread objects from GitHub API.
- **Side Effects**: None (Read-only).

### `post_reply(repo: str, pr_number: str, thread_id: str, body: str) -> str`
- **Input**: Repository, PR, thread ID, and reply Markdown.
- **Output**: URL of the created comment.
- **Side Effects**: Creates a comment on GitHub.

### `resolve_thread(repo: str, pr_number: str, thread_id: str) -> bool`
- **Input**: Repository, PR, thread ID.
- **Output**: `True` if successful.
- **Side Effects**: Marks thread as resolved on GitHub.

## Error Handling
All methods must raise `GitHubError` for transient or terminal API failures, classifying them by type (Auth, RateLimit, NotFound, etc.).
