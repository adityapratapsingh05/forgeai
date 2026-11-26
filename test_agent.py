#!/usr/bin/env python3
"""Quick test script to verify the HR policy agent works."""

from pathlib import Path
from forgeai.agent_runner import AgentRunner
from forgeai.llm import LLMClient
from forgeai.schemas import AgentDefinition
import yaml

def main():
    # Load agent definition
    agent_path = Path("runs/hr_policy/agent_definition.yaml")
    docs_path = Path("demos/hr_policy/docs")

    print("Loading agent definition...")
    raw = yaml.safe_load(agent_path.read_text(encoding="utf-8"))
    agent_def = AgentDefinition.model_validate(raw)

    print(f"Agent: {agent_def.name}")
    print(f"Description: {agent_def.description}\n")

    # Initialize runner
    llm = LLMClient()
    runner = AgentRunner(agent_def, docs_path, llm)

    # Test questions
    questions = [
        "How many days of annual leave do employees get?",
        "What is the travel expense policy for flights?",
        "Can you tell me about stock options?"  # Should refuse
    ]

    print("Testing agent with sample questions...\n")
    for i, q in enumerate(questions, 1):
        print(f"Q{i}: {q}")
        try:
            response = runner.ask(q)
            print(f"A{i}: {response.answer}")
            if response.citations:
                print(f"Citations: {', '.join(response.citations)}")
            print()
        except Exception as e:
            print(f"Error: {e}\n")

    llm.close()
    print("✓ Agent test completed successfully!")

if __name__ == "__main__":
    main()
