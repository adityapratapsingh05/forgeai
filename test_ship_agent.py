#!/usr/bin/env python3
"""Manual live-LLM smoke test for the ship spares agent."""
from pathlib import Path

from forgeai.agent_runner import AgentRunner
from forgeai.llm import LLMClient
from runner.chat import load_agent_definition


def main() -> None:
    print("=== Testing Ship Spares Agent ===\n")

    agent_def = load_agent_definition(Path("runs/ship_spares/agent_definition.yaml"))
    llm = LLMClient()
    questions = [
        "What is the lead time for Main Engine Oil Cooler?",
        "What are the payment terms for SUP-01?",
        "How much does the Navigation Radar Antenna cost?"
    ]

    try:
        runner = AgentRunner(
            agent=agent_def,
            docs_dir=Path("demos/ship_spares/docs"),
            llm_client=llm,
        )
        for i, question in enumerate(questions, 1):
            print(f"Q{i}: {question}")
            response = runner.ask(question)
            print(f"A{i}: {response.answer[:200]}...")
            print(f"Citations: {response.citations}")
            print()
    finally:
        llm.close()

    print("✅ Ship Spares agent test complete\n")


if __name__ == "__main__":
    main()
