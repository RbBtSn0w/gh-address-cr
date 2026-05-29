# Research: Dynamic CR Replies & Severity Accuracy

## Decision: Expand Severity scale to P0-P4
- **Rationale**: The current P1-P3 scale is insufficient for distinguishing between critical blockers (P0) and minor stylistic suggestions (P4). A 5-level scale aligns with industry standards (e.g., Google/Meta severity levels).
- **Alternatives considered**: 3-level scale (too coarse), naming only (e.g., "Critical/High/Medium/Low" - less deterministic than P-scale for machine-readable rules).

## Decision: Adopt "Structured but Rich" Template Refactoring
- **Rationale**: The current implementation treats the "why" rationale as a single string field, often rendered as a single bullet point. Refactoring `reply_templates.py` to support multi-line rationales and updating the markdown assets to use more descriptive, less formulaic language will address the "rigidity" concern.
- **Alternatives considered**: Natural Conversation (too hard to audit), Strictly Rubric-based (replaces one rigidity with another).

## Decision: Canonical Severity Rubric Artifact
- **Rationale**: To ensure accuracy across different LLMs, a formal rubric must be defined in the agent's prompt context (via `openai.yaml`). This rubric will define specific criteria for each P-level (e.g., P0 requires potential for data loss or crash).
- **Alternatives considered**: Hardcoding rules in Python (too inflexible for evolving review needs).

## Finding: Rich String Handling
The `fix_reply` helper currently accepts a list of strings. If we want multi-paragraph rationales, we must ensure that the `why` field (index 4 in the list) is handled as a multi-line string and correctly formatted in the markdown output without breaking the bulleted structure if multiple points are provided.

## Finding: GitHub Emoji/Label Mapping
- P0: 🛑 **Blocker**
- P1: 🔴 **Critical**
- P2: 🟠 **Major**
- P3: 🟡 **Minor**
- P4: 🔘 **Nit**
This mapping provides immediate visual signal to human reviewers.
