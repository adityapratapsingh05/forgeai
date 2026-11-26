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

# ForgeAI dashboard styling
st.markdown("""
<style>
    :root {
        --forge-bg: #0b1020;
        --forge-panel: #111a2e;
        --forge-border: rgba(148, 163, 184, 0.16);
        --forge-text: #e8eefb;
        --forge-muted: #9aa9c2;
        --forge-cyan: #62d5e8;
        --forge-violet: #9b8cff;
    }

    .stApp {
        color: var(--forge-text);
        background:
            radial-gradient(ellipse at 12% 0%, rgba(52, 94, 172, 0.18), transparent 34rem),
            radial-gradient(ellipse at 92% 18%, rgba(109, 78, 196, 0.13), transparent 30rem),
            var(--forge-bg);
    }

    [data-testid="stHeader"] {
        background: rgba(11, 16, 32, 0.72);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #101a30 0%, #0c1425 100%);
        border-right: 1px solid var(--forge-border);
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: var(--forge-muted);
    }

    .block-container {
        max-width: 1440px;
        padding-top: 2.4rem;
        padding-bottom: 4rem;
    }

    .forge-hero {
        position: relative;
        overflow: hidden;
        padding: 2rem 2.2rem;
        margin: 0 0 1.8rem;
        border: 1px solid rgba(133, 161, 213, 0.22);
        border-radius: 24px;
        background: linear-gradient(118deg, rgba(23, 39, 68, 0.97), rgba(20, 27, 53, 0.94) 56%, rgba(44, 35, 83, 0.88));
        box-shadow: 0 24px 70px rgba(0, 0, 0, 0.25);
    }

    .forge-hero:after {
        content: "";
        position: absolute;
        width: 18rem;
        height: 18rem;
        right: -5rem;
        top: -9rem;
        border-radius: 50%;
        background: rgba(98, 213, 232, 0.12);
        filter: blur(2px);
    }

    .forge-eyebrow {
        color: var(--forge-cyan);
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        margin-bottom: 0.55rem;
    }

    .forge-hero h1 {
        color: #f5f7ff;
        font-size: clamp(2rem, 4vw, 3.1rem);
        line-height: 1.08;
        letter-spacing: -0.045em;
        margin: 0;
    }

    .forge-hero p {
        color: #b6c4dc;
        font-size: 1.03rem;
        margin: 0.85rem 0 0;
        max-width: 48rem;
    }

    [data-testid="stTabs"] [role="tablist"] {
        gap: 0.55rem;
        border-bottom: 1px solid var(--forge-border);
    }

    [data-testid="stTabs"] button[role="tab"] {
        color: #aab8d0;
        border-radius: 12px 12px 0 0;
        padding: 0.8rem 1.15rem;
    }

    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
        color: #f5f7ff;
        border-bottom-color: var(--forge-cyan);
        background: rgba(98, 213, 232, 0.08);
    }

    h2, h3 {
        color: #f2f5ff;
        letter-spacing: -0.025em;
    }

    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stSelectbox"] [data-baseweb="select"] > div,
    [data-testid="stNumberInput"] input {
        color: var(--forge-text);
        background: rgba(13, 22, 39, 0.9);
        border-color: rgba(148, 163, 184, 0.25);
        border-radius: 10px;
    }

    [data-testid="stFileUploader"] section {
        border: 1px dashed rgba(98, 213, 232, 0.38);
        border-radius: 14px;
        background: rgba(17, 26, 46, 0.6);
    }

    [data-testid="stFileUploader"] section:hover {
        border-color: var(--forge-cyan);
    }

    .stButton > button,
    [data-testid="stFormSubmitButton"] button {
        border-radius: 10px;
        font-weight: 650;
        transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
    }

    .stButton > button:hover,
    [data-testid="stFormSubmitButton"] button:hover {
        transform: translateY(-1px);
        box-shadow: 0 8px 22px rgba(68, 127, 210, 0.2);
    }

    [data-testid="stExpander"] {
        border: 1px solid var(--forge-border);
        border-radius: 12px;
        background: rgba(17, 26, 46, 0.62);
    }

    [data-testid="stAlert"] {
        border-radius: 12px;
    }

    .forge-caption {
        color: var(--forge-muted);
        font-size: 0.9rem;
        margin-top: -0.45rem;
        margin-bottom: 1.2rem;
    }

    @media (max-width: 700px) {
        .block-container { padding: 1.3rem 1rem 3rem; }
        .forge-hero { padding: 1.5rem; border-radius: 18px; }
    }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<section class="forge-hero">
    <div class="forge-eyebrow">ForgeAI · Agent workspace</div>
    <h1>Build agents that know their sources.</h1>
    <p>Turn your documents into useful, evaluated AI agents — then put them to work in a grounded chat.</p>
</section>
""", unsafe_allow_html=True)

settings = load_settings()
st.sidebar.markdown("## ⚙️ Workspace")
st.sidebar.caption("Connected model configuration")
st.sidebar.markdown(f"**Model**  \n`{settings.llm_model}`")
st.sidebar.markdown(f"**Embeddings**  \n`{settings.embed_model}`")
st.sidebar.markdown(f"**Judge**  \n`{settings.judge_model}`")
st.sidebar.caption(f"API endpoint: {settings.llm_base_url}")
st.sidebar.divider()
st.sidebar.caption("Configure via `.env` or Streamlit secrets. API keys are never displayed here.")

tab_factory, tab_runner = st.tabs(["Agent Factory", "Chat Runner"])

with tab_factory:
    st.subheader("Create an agent")
    st.markdown('<p class="forge-caption">Define its purpose, add trusted source documents, and let ForgeAI build and evaluate it.</p>', unsafe_allow_html=True)
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
    st.markdown("#### Evaluation settings")
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
    st.subheader("Your agent runs")
    st.markdown('<p class="forge-caption">Review generated reports, definitions, and optimization artifacts.</p>', unsafe_allow_html=True)
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
    st.subheader("Chat with an agent")
    st.markdown('<p class="forge-caption">Load a generated agent and ask questions grounded in its document library.</p>', unsafe_allow_html=True)

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
        for q, a, citations in st.session_state.chat_history:
            with st.chat_message("user"):
                st.markdown(q)
            with st.chat_message("assistant", avatar="✨"):
                st.markdown(a)
                if citations:
                    st.caption(f"📚 Sources: {', '.join(citations)}")

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
                    with st.chat_message("assistant", avatar="✨"):
                        st.markdown(resp.answer)
                        if resp.citations:
                            st.caption(f"📚 Sources: {', '.join(resp.citations)}")

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

