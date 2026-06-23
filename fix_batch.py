path = 'src/gh_address_cr/core/agent_batch.py'
content = open(path).read()
if 'from datetime import datetime' not in content:
    content = 'from datetime import datetime\n' + content
content = content.replace('def _select_batch_target_items(session, *, agent_id: str, files: list[str] | None):',
                          'def _select_batch_target_items(session: dict[str, Any], *, agent_id: str, files: list[str] | None) -> list[tuple[str, dict[str, Any]]]:')
content = content.replace('def _ensure_batch_classification_evidence(session, item, *, item_id, agent_id, ledger) -> None:',
                          'def _ensure_batch_classification_evidence(session: dict[str, Any], item: dict[str, Any], *, item_id: str, agent_id: str, ledger: Any) -> None:')
content = content.replace('def _build_fixer_action_request(session, repo, pr_number, *, item, lease_id, request_id) -> dict[str, Any]:',
                          'def _build_fixer_action_request(session: dict[str, Any], repo: str, pr_number: str, *, item: dict[str, Any], lease_id: str, request_id: str) -> dict[str, Any]:')
content = content.replace('def _reconcile_existing_lease(session, repo, pr_number, *, item, item_id, existing_lease, agent_id, ledger) -> dict[str, Any]:',
                          'def _reconcile_existing_lease(session: dict[str, Any], repo: str, pr_number: str, *, item: dict[str, Any], item_id: str, existing_lease: dict[str, Any], agent_id: str, ledger: Any) -> dict[str, Any]:')
old_lease = """def _lease_new_github_thread(
    session, repo, pr_number, *, item, item_id, agent_id, ledger, current_time, newly_leased_items
) -> dict[str, Any] | None:"""
new_lease = """def _lease_new_github_thread(
    session: dict[str, Any], repo: str, pr_number: str, *, item: dict[str, Any], item_id: str, agent_id: str, ledger: Any, current_time: datetime, newly_leased_items: list[tuple[str, dict[str, Any]]]
) -> dict[str, Any] | None:"""
content = content.replace(old_lease, new_lease)
content = content.replace('def _rollback_newly_leased_items(session, newly_leased_items) -> None:',
                          'def _rollback_newly_leased_items(session: dict[str, Any], newly_leased_items: list[tuple[str, dict[str, Any]]]) -> None:')
content = content.replace('def _load_existing_batch_skeleton(batch_skeleton_path) -> tuple[dict, dict]:',
                          'def _load_existing_batch_skeleton(batch_skeleton_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:')
content = content.replace('def _build_batch_skeleton(agent_id, leased_items, existing_items_replies, existing_common) -> dict[str, Any]:',
                          'def _build_batch_skeleton(agent_id: str, leased_items: list[dict[str, Any]], existing_items_replies: dict[str, Any], existing_common: dict[str, Any]) -> dict[str, Any]:')
open(path, 'w').write(content)
