# Quickstart: Dynamic CR Replies

## Testing the New Severity Scale
To verify the P0-P4 scale and rich rendering locally:

1.  **Run the unit tests**:
    ```bash
    python3 -m unittest tests/core/test_reply_templates.py
    ```

2.  **Generate a sample P0 reply**:
    ```bash
    python3 skill/scripts/generate_reply.py --severity P0 \
      "0123456" "src/main.py" "pytest" "Passed" \
      "This fixes a critical SQL injection vulnerability in the login path. 
       We now use parameterized queries across all database interactions.
       
       This change was verified against a suite of known malicious inputs."
    ```

## Rubric Inspection
The canonical rubric used by agents is located in `skill/agents/openai.yaml`. Ensure it is updated when changing severity criteria.
