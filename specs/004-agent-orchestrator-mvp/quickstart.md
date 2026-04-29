# Quickstart: Orchestrator MVP

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