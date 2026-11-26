#!/usr/bin/env python3
"""Quick test of Ship Spares agent"""
import sys
from runner.chat import load_agent_definition, AgentRunner

def test_ship_agent():
    print("=== Testing Ship Spares Agent ===\n")

    # Load agent
    agent_def = load_agent_definition("runs/ship_spares/agent_definition.yaml")
    runner = AgentRunner(agent_def, "demos/ship_spares/docs", debug=False)

    # Test questions
    questions = [
        "What is the lead time for Main Engine Oil Cooler?",
        "What are the payment terms for SUP-01?",
        "How much does the Navigation Radar Antenna cost?"
    ]

    for i, question in enumerate(questions, 1):
        print(f"Q{i}: {question}")
        response = runner.run_query(question)
        print(f"A{i}: {response['answer'][:200]}...")
        print(f"Citations: {response.get('citations', [])}")
        print()

    print("✅ Ship Spares agent test complete\n")

if __name__ == "__main__":
    test_ship_agent()
