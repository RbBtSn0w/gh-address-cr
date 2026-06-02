# Quickstart: Orchestrator MVP

> **Historical note:** Superseded by `specs/012-cli-skill-sync` for current
> skill execution guidance. `skill/scripts` and `scripts/cli.py` examples below
> describe the earlier shim-era contract and are not current runnable paths.

## 1. Start Orchestration
```bash
python3 skill/scripts/cli.py agent orchestrate start owner/repo 123
```

## 2. Step and Receive Worker Packet
```bash
python3 skill/scripts/cli.py agent orchestrate step owner/repo 123 > packet.json
```

## 3. Emulate Worker
Create a response for the item identified in `packet.json` and save it to the specified `response_path`.

## 4. Resume After Interruption
```bash
python3 skill/scripts/cli.py agent orchestrate resume owner/repo 123
```
