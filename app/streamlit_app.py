"""Enhanced Streamlit UI for ForgeAI Factory & Generic Chat Runner."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from datetime import datetime

import streamlit as st
import yaml

from forgeai.agent_runner import AgentRunner
from forgeai.config import load_settings
from forgeai.factory import run_factory_pipeline
from forgeai.llm import LLMClient
from forgeai.schemas import AgentDefinition

st.set_page_config(
    page_title="ForgeAI — Agent Factory",
    layout="wide",
    page_icon="🤖",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .stTextInput>div>div>input, .stTextArea>div>div>textarea {
        background-color: #f0f2f6;
    }
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        border-left: 4px solid #1f77b4;
    }
    .citation {
        font-size: 0.85rem;
        color: #666;
        font-style: italic;
    }
</style>
""", unsafe_allow_html=True)

st.title("🤖 ForgeAI — Autonomous Agent Factory & Runner")

settings = load_settings()
st.sidebar.header("Backend Configuration")
st.sidebar.text(f"Base URL: {settings.llm_base_url}")
st.sidebar.text(f"Model: {settings.llm_model}")
st.sidebar.text(f"Embed: {settings.embed_model}")
st.sidebar.text(f"Judge: {settings.judge_model}")
st.sidebar.caption("Configure via .env or Streamlit secrets (LLM_BASE_URL, LLM_MODEL, LLM_API_KEY, EMBED_MODEL).")

tab_factory, tab_runner = st.tabs(["Agent Factory", "Chat Runner"])

with tab_factory:
    st.subheader("Build & Optimize an Agent from Brief + Documents")
    run_name = st.text_input("Run Name", value="streamlit_run")
    brief = st.text_area(
        "One-Paragraph Brief",
        height=120,
        placeholder="Describe what the agent should do, target audience, tone, and boundaries...",
    )
    uploaded_files = st.file_uploader(
        "Upload Documents (PDF, MD, TXT, CSV, DOCX)",
        accept_multiple_files=True,
    )
    col1, col2, col3 = st.columns(3)
    max_iters = col1.number_input("Max Optimizer Iters", min_value=0, max_value=3, value=3)
    eval_count = col2.number_input("Eval Cases", min_value=20, max_value=50, value=25)
    target_score = col3.slider("Target Dev Score", min_value=0.5, max_value=0.98, value=0.85)

    if st.button("Run ForgeAI Factory (Unattended)", type="primary"):
        if not brief.strip() or not uploaded_files:
            st.error("Please provide both a brief and at least one document.")
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                docs_dir = Path(tmpdir) / "docs"
                docs_dir.mkdir(parents=True, exist_ok=True)
                for uf in uploaded_files:
                    (docs_dir / uf.name).write_bytes(uf.read())
                with st.spinner("Running ForgeAI pipeline (intake -> groundability -> generate -> evalgen -> optimize -> report)..."):
                    try:
                        out_dir = run_factory_pipeline(
                            brief_text=brief,
                            docs_dir=docs_dir,
                            run_name=run_name,
                            non_interactive=True,
                            max_iters=int(max_iters),
                            target_score=float(target_score),
                            eval_count=int(eval_count),
                            force=True,
                        )
                        st.success(f"Run completed! Artifacts saved to `{out_dir}`.")
                        st.markdown((out_dir / "report.md").read_text(encoding="utf-8"))
                    except Exception as exc:
                        st.error(f"Factory failed: {exc}")

    st.divider()
    st.subheader("Inspect Existing Runs")
    runs_dir = Path("runs")
    available_runs = sorted([p.name for p in runs_dir.iterdir() if p.is_dir()]) if runs_dir.exists() else []
    if available_runs:
        chosen = st.selectbox("Select Run", available_runs)
        rpath = runs_dir / chosen
        if (rpath / "report.md").exists():
            with st.expander("View report.md", expanded=True):
                st.markdown((rpath / "report.md").read_text(encoding="utf-8"))
        if (rpath / "agent_definition.yaml").exists():
            with st.expander("View agent_definition.yaml"):
                st.code((rpath / "agent_definition.yaml").read_text(encoding="utf-8"), language="yaml")
        if (rpath / "iteration_log.md").exists():
            with st.expander("View iteration_log.md"):
                st.markdown((rpath / "iteration_log.md").read_text(encoding="utf-8"))
        if (rpath / "groundability_report.json").exists():
            with st.expander("View groundability_report.json"):
                st.json(json.loads((rpath / "groundability_report.json").read_text(encoding="utf-8")))
    else:
        st.info("No runs found under `runs/` yet.")

with tab_runner:
    st.subheader("💬 Chat with Any Generated Agent")

    # Initialize session state for chat history
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "runner" not in st.session_state:
        st.session_state.runner = None
    if "llm" not in st.session_state:
        st.session_state.llm = None

    runs_dir = Path("runs")
    available_runs = sorted([p.name for p in runs_dir.iterdir() if p.is_dir()]) if runs_dir.exists() else []

    col1, col2 = st.columns([2, 1])

    with col1:
        agent_path_str = st.text_input(
            "Agent Definition Path",
            value=f"runs/{available_runs[0]}/agent_definition.yaml" if available_runs else "runs/hr_policy/agent_definition.yaml",
        )

    with col2:
        docs_path_str = st.text_input(
            "Documents Folder",
            value="demos/hr_policy/docs",
        )

    debug_mode = st.checkbox("🔍 Show debug info (retrieved chunks & tools)", value=False)

    # Load agent button
    if st.button("Load Agent", type="primary"):
        a_path = Path(agent_path_str)
        d_path = Path(docs_path_str)
        if not a_path.exists() or not d_path.exists():
            st.error("❌ Agent definition or docs folder not found.")
        else:
            try:
                definition = AgentDefinition.model_validate(
                    yaml.safe_load(a_path.read_text(encoding="utf-8"))
                )
                if st.session_state.llm:
                    st.session_state.llm.close()
                st.session_state.llm = LLMClient()
                st.session_state.runner = AgentRunner(
                    agent=definition,
                    docs_dir=d_path,
                    llm_client=st.session_state.llm
                )
                st.session_state.chat_history = []
                st.success(f"✅ Loaded agent: **{definition.name}**")
                st.info(f"📝 {definition.description}")
            except Exception as exc:
                st.error(f"❌ Failed to load agent: {exc}")

    st.divider()

    # Chat interface
    if st.session_state.runner:
        # Display chat history
        for i, (q, a, citations) in enumerate(st.session_state.chat_history):
            with st.container():
                st.markdown(f"**You:** {q}")
                st.markdown(f"**Agent:** {a}")
                if citations:
                    st.caption(f"📚 Citations: {', '.join(citations)}")
                st.divider()

        # Input form
        with st.form(key="question_form", clear_on_submit=True):
            user_q = st.text_input("Ask a question:", key="user_input")
            submit_btn = st.form_submit_button("Send", type="primary")

        if submit_btn and user_q.strip():
            with st.spinner("Thinking..."):
                try:
                    resp = st.session_state.runner.ask(user_q)
                    st.session_state.chat_history.append((user_q, resp.answer, resp.citations))

                    # Display the latest response
                    st.markdown(f"**Agent:** {resp.answer}")
                    if resp.citations:
                        st.caption(f"📚 Citations: {', '.join(resp.citations)}")

                    if debug_mode:
                        with st.expander("🔍 Debug Information"):
                            if resp.tool_calls:
                                st.write("**Tool Calls:**")
                                st.json([tc.model_dump() for tc in resp.tool_calls])
                            if resp.retrieved_chunks:
                                st.write("**Retrieved Chunks:**")
                                for h in resp.retrieved_chunks:
                                    st.text(f"[{h.source_file}] score={h.score:.3f}")
                                    st.text(f"  {h.text[:200]}...")
                except Exception as exc:
                    st.error(f"❌ Error: {exc}")

        # Clear chat button
        if st.button("🗑️ Clear Chat History"):
            st.session_state.chat_history = []
            st.rerun()
    else:
        st.info("👆 Load an agent to start chatting")

