#!/usr/bin/env python3
"""Quick test of HR Policy agent"""
from pathlib import Path
from runner.chat import load_agent_definition
from forgeai.agent_runner import AgentRunner

def test_hr_agent():
    print("=== Testing HR Policy Agent ===\n")

    # Load agent
    agent_def = load_agent_definition(Path("runs/hr_policy/agent_definition.yaml"))
    runner = AgentRunner(agent_def, Path("demos/hr_policy/docs"), debug=False)

    # Test questions
    questions = [
        "How many days of annual leave do I get?",
        "What is the expense limit for meals when traveling?",
        "Can I use company equipment for personal projects?"
    ]

    for i, question in enumerate(questions, 1):
        print(f"Q{i}: {question}")
        response = runner.run_query(question)
        print(f"A{i}: {response['answer'][:200]}...")
        print(f"Citations: {response.get('citations', [])}")
        print()

    print("✅ HR Policy agent test complete\n")

if __name__ == "__main__":
    test_hr_agent()
