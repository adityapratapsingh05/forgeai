# ForgeAI Quick Start Guide

## Setup with Gemini (no Ollama required)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Gemini
```bash
cp .env.example .env
```

Create a key in [Google AI Studio](https://aistudio.google.com/apikey), then set
`LLM_API_KEY` in `.env`. Gemini is used for chat; FastEmbed generates embeddings
locally with `sentence-transformers/all-MiniLM-L6-v2` and downloads the model
on first use. Never paste the key into source files or commit `.env`.

Ollama remains an optional backend. To use it instead, set the endpoint,
generation model, embedding model, and API key in `.env`.

## 🎯 Quick Demo

### Run the Streamlit UI (Recommended)
```bash
streamlit run app/streamlit_app.py
```

Then:
1. Go to the **"Chat Runner"** tab
2. Click **"Load Agent"** (uses pre-generated HR policy agent)
3. Ask questions like:
   - "How many days of annual leave do employees get?"
   - "What is the travel expense policy?"
   - "What about stock options?" (should refuse - out of scope)

### Run CLI Chat
```bash
python -m runner.chat \
  --agent runs/hr_policy/agent_definition.yaml \
  --docs demos/hr_policy/docs \
  --debug
```

## 🏭 Build Your Own Agent

### Option 1: Using Pre-built Demos
```bash
# HR Policy Assistant
make demo-hr

# Ship Spares Assistant (with CSV lookup & calculator)
make demo-spares
```

### Option 2: Custom Agent from Scratch
```bash
python -m forgeai.factory \
  --brief path/to/your_brief.txt \
  --docs path/to/your_docs_folder \
  --run-name my_agent \
  --non-interactive \
  --max-questions 3 \
  --max-iters 2
```

The brief should be 1 paragraph describing:
- What the agent should do
- Target audience
- Tone (professional, casual, technical)
- What topics it should refuse

## 📂 Project Structure

```
forgeai/
├── factory.py          # Main orchestrator
├── intake.py           # Requirement gathering
├── groundability.py    # Verifies docs can answer the brief
├── generator.py        # Creates agent definition
├── evalgen.py          # Generates test cases
├── judge.py            # Evaluates agent responses
├── optimizer.py        # Improves agent iteratively
├── agent_runner.py     # Shared execution engine
└── tools/              # Built-in tools (calculator, CSV, weather)

runs/
└── <run_name>/
    ├── agent_definition.yaml   # Final agent spec
    ├── requirements.json       # Extracted requirements
    ├── eval_set.json          # Test cases
    ├── scorecard.json         # Performance metrics
    └── report.md              # Honest assessment

demos/
├── hr_policy/          # Demo A: HR policy docs
└── ship_spares/        # Demo B: Ship spare parts catalog
```

## ✅ What Works

- ✅ All 29 unit tests passing
- ✅ Document ingestion (PDF, MD, TXT, CSV, DOCX)
- ✅ Hybrid BM25 + embedding retrieval
- ✅ Automatic tool selection (calculator, CSV lookup, weather, date)
- ✅ Groundability checking (refuses unsupported topics)
- ✅ Agent definition generation
- ✅ Interactive Streamlit UI with chat history
- ✅ Generic CLI chat runner
- ✅ Evaluation generation with quality filters
- ✅ Calibrated LLM-as-judge with deterministic fallbacks

## 🔧 Troubleshooting

### "No module named 'rank_bm25'"
```bash
pip install rank_bm25
```

### "Connection refused" or API authentication errors
```bash
# Check LLM_BASE_URL and LLM_API_KEY in your local .env.
# For Gemini, use https://generativelanguage.googleapis.com/v1beta/openai/
```

### Provider returns HTTP 429
- The client honors `Retry-After` and provider reset hints, waiting up to 60 seconds before retrying.
- The Makefile demo targets use 20 eval cases and one optimizer iteration to limit token usage.
- Run demos sequentially and wait for the provider's stated reset time before retrying after a final 429.

### Factory runs very slowly
- Check your provider's rate limits and model latency
- Reduce iterations: `--max-iters 1`
- Reduce eval cases with `--eval-count` (the factory still enforces a 20-case minimum)

### Agent refuses everything
- Check `groundability_report.json` in your run folder
- Your documents may not support the brief
- Try narrowing the brief scope

## 📖 Next Steps

1. **Read PLAN.md** - Architecture deep dive
2. **Check runs/hr_policy/** - See example outputs
3. **Experiment** - Create agents for your own documents
4. **Extend** - Add custom tools in `forgeai/tools/`

## 🎓 Key Concepts

**Brief** → One paragraph describing the agent's job

**Intake** → Asks ≤5 clarifying questions (or runs unattended)

**Groundability** → Checks if documents support the brief

**Agent Definition** → YAML spec with system prompt, tools, retrieval config

**Eval Set** → Synthetic test cases filtered for quality

**Critic-Optimizer** → Iteratively improves agent (max 3 iterations)

**Honest Report** → Tells you what still fails and why
