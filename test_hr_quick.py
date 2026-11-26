#!/usr/bin/env python3
"""Manual live-LLM smoke test for the HR policy agent."""
from pathlib import Path

from forgeai.agent_runner import AgentRunner
from forgeai.llm import LLMClient
from runner.chat import load_agent_definition


def main() -> None:
    print("=== Testing HR Policy Agent ===\n")

    agent_def = load_agent_definition(Path("runs/hr_policy/agent_definition.yaml"))
    llm = LLMClient()
    questions = [
        "How many days of annual leave do I get?",
        "What is the expense limit for meals when traveling?",
        "Can I use company equipment for personal projects?"
    ]

    try:
        runner = AgentRunner(
            agent=agent_def,
            docs_dir=Path("demos/hr_policy/docs"),
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

    print("✅ HR Policy agent test complete\n")


if __name__ == "__main__":
    main()
