#!/bin/bash
# ForgeAI Demo Script - Quick demonstration of all features

set -e

echo "🤖 ForgeAI Demo Script"
echo "====================="
echo ""

echo "Using the OpenAI-compatible LLM and embedding endpoints configured in .env."
echo "Ollama is optional; no local model download is required."
echo ""

# Run tests
echo "🧪 Running test suite..."
python3 -m pytest -v --tb=short
echo ""

# Check if demo documents exist
if [ ! -f "demos/hr_policy/docs/leave_policy.md" ]; then
    echo "📝 Generating demo documents..."
    python3 -m demos.synthesize_docs
    echo ""
fi

echo "✅ Demo documents ready"
echo ""

# Show available runs
echo "📂 Available agent runs:"
if [ -d "runs" ]; then
    ls -1 runs/
else
    echo "  (none yet)"
fi
echo ""

# Menu
echo "What would you like to do?"
echo ""
echo "1) Launch Streamlit UI (recommended)"
echo "2) Chat with HR Policy agent (CLI)"
echo "3) Build new agent from HR policy docs"
echo "4) View HR policy agent definition"
echo "5) Exit"
echo ""
read -p "Enter choice [1-5]: " choice

case $choice in
    1)
        echo ""
        echo "🚀 Launching Streamlit UI..."
        echo "   Open http://localhost:8501 in your browser"
        echo ""
        streamlit run app/streamlit_app.py
        ;;
    2)
        echo ""
        echo "💬 Starting CLI chat with HR Policy agent..."
        echo ""
        if [ -f "runs/hr_policy/agent_definition.yaml" ]; then
            python3 -m runner.chat \
                --agent runs/hr_policy/agent_definition.yaml \
                --docs demos/hr_policy/docs \
                --debug
        else
            echo "❌ Agent not found. Run option 3 first to build it."
        fi
        ;;
    3)
        echo ""
        echo "🏭 Building agent from HR policy documents..."
        echo "   This will take 2-5 minutes with the 7B model"
        echo ""
        python3 -m forgeai.factory \
            --brief demos/hr_policy/brief.txt \
            --docs demos/hr_policy/docs \
            --run-name hr_policy_demo_$(date +%s) \
            --non-interactive \
            --eval-count 20 \
            --max-questions 2 \
            --max-iters 1 \
            --target 0.7
        echo ""
        echo "✅ Agent built successfully!"
        echo "   Check runs/ folder for outputs"
        ;;
    4)
        echo ""
        if [ -f "runs/hr_policy/agent_definition.yaml" ]; then
            cat runs/hr_policy/agent_definition.yaml
        else
            echo "❌ Agent not found. Run option 3 first to build it."
        fi
        ;;
    5)
        echo "Goodbye! 👋"
        exit 0
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac
