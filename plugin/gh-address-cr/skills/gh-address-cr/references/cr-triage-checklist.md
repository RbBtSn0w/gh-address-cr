# CR Triage Checklist

Use this checklist before deciding to fix a review item.

## 1. Validate The Claim

- Is the claim reproducible in current HEAD?
- Is it directly supported by the current code, tests, or runtime contract?
- If not reproducible yet, is it merely unclear rather than confirmed?

## 2. Classify The Impact

- Is this correctness, state consistency, concurrency, runtime, compatibility, packaging, or CI?
- Or is it style, naming, wording, or a structural preference?
- Does it affect users or only internal code aesthetics?

## 3. Check Scope Fit

- Can this be fixed locally in the current PR?
- Does the suggestion require a new contract, new public behavior, or broader refactor?
- Would fixing it here enlarge the PR beyond its intended purpose?

## 4. Choose A Decision

- `fix`: confirmed and in scope; change code and verify
- `clarify`: current behavior is intentional; explain without code change
- `defer`: issue is real but should move to a follow-up PR
- `reject`: technically unsound or conflicts with an explicit contract

If any answer remains unclear, do not implement yet. Escalate to `NEEDS_HUMAN` instead of guessing.

## 5. Before Resolving The Item

- Did we verify with targeted tests?
- Did we avoid unrelated refactors?
- Did we record the decision rationale?
- Did we post evidence: commit, touched files, validation command/result?
- Should the thread be resolved now, or kept open with a concrete plan?
