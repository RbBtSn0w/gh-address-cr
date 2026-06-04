# Contract: Logic Validation Signal

## Purpose

Surface lightweight evidence and state consistency risks without turning validation into a second review producer or hidden AI judge.

## Signal Shape

```json
{
  "signal_id": "signal_123",
  "item_id": "github-thread:THREAD_ID",
  "signal_type": "missing_required_evidence",
  "confidence": "high",
  "explanation": "The response claims completion but lacks validation evidence.",
  "recommended_action": "supplement_evidence",
  "gate_effect": "blocking"
}
```

## Signal Types

- `missing_required_evidence`
- `state_contradiction`
- `unsupported_completion_claim`
- `reply_classification_inconsistency`
- `low_confidence_advisory`

## Required Behavior

- Validation signals are advisory by default.
- Signals become blocking only for missing required evidence, runtime state contradiction, or false completion evidence.
- Blocking signals must explain the contradiction and provide an actionable next step.
- Low-confidence advisory signals must not block normal completion.
- Signals cannot create findings, mutate work item state, publish replies, resolve threads, or replace final-gate evidence.

## Gate Interaction

Final gate may include validation diagnostics, but completion truth remains based on runtime state, reply/resolve evidence, required validation evidence, and final-gate checks.
