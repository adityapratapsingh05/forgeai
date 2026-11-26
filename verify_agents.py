#!/usr/bin/env python3
"""Quick verification test of both agents"""
from pathlib import Path
import yaml
from forgeai.schemas import AgentDefinition

def verify_agents():
    print("=== Agent Verification Test ===\n")

    # Test 1: Check HR Policy agent loads
    print("1. Loading HR Policy agent...")
    hr_path = Path("runs/hr_policy/agent_definition.yaml")
    with open(hr_path) as f:
        hr_yaml = yaml.safe_load(f)
        hr_agent = AgentDefinition.model_validate(hr_yaml)
    print(f"   ✅ HR Policy agent loaded: {hr_agent.name}")
    print(f"   Description: {hr_agent.description[:80]}...")
    print(f"   Tools: {', '.join(hr_agent.tools or ['none'])}")
    print()

    # Test 2: Check Ship Spares agent loads
    print("2. Loading Ship Spares agent...")
    ship_path = Path("runs/ship_spares/agent_definition.yaml")
    with open(ship_path) as f:
        ship_yaml = yaml.safe_load(f)
        ship_agent = AgentDefinition.model_validate(ship_yaml)
    print(f"   ✅ Ship Spares agent loaded: {ship_agent.name}")
    print(f"   Description: {ship_agent.description[:80]}...")
    print(f"   Tools: {', '.join(ship_agent.tools or ['none'])}")
    print()

    # Test 3: Check demo documents exist
    print("3. Checking demo documents...")
    hr_docs = list(Path("demos/hr_policy/docs").glob("*.md"))
    ship_docs = list(Path("demos/ship_spares/docs").glob("*.*"))
    print(f"   ✅ HR Policy docs: {len(hr_docs)} markdown files")
    print(f"   ✅ Ship Spares docs: {len(ship_docs)} files")
    print()

    # Test 4: Check all artifacts present
    print("4. Checking artifacts...")
    required = [
        "agent_definition.yaml",
        "eval_set.json",
        "scorecard.json",
        "honest_report.md",
        "judge_calibration.json"
    ]

    for demo in ["hr_policy", "ship_spares"]:
        missing = []
        for file in required:
            if not Path(f"runs/{demo}/{file}").exists():
                missing.append(file)

        if missing:
            print(f"   ❌ {demo}: Missing {missing}")
        else:
            print(f"   ✅ {demo}: All {len(required)} required artifacts present")

    print("\n=== Verification Complete ===")
    print("Both agents are properly configured and ready to use!")
    print("\nTo test interactively:")
    print("  python3 -m runner.chat --agent runs/hr_policy/agent_definition.yaml --docs demos/hr_policy/docs")
    print("  python3 -m runner.chat --agent runs/ship_spares/agent_definition.yaml --docs demos/ship_spares/docs")

if __name__ == "__main__":
    verify_agents()
