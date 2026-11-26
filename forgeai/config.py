"""Configuration and prompt loading utilities for ForgeAI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from forgeai import __version__

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
PROMPTS_DIR = PACKAGE_DIR / "prompts"

console = Console()


@dataclass(frozen=True)
class Settings:
    """Runtime configuration loaded from environment variables and .env."""

    llm_base_url: str
    llm_model: str
    llm_api_key: str
    embed_model: str
    judge_model: str
    timeout_seconds: float
    max_retries: int
    cache_dir: Path
    factory_version: str = __version__

    @property
    def same_judge_model(self) -> bool:
        """Return True if the judge uses the same model as the generator/agent."""
        return self.judge_model.strip() == self.llm_model.strip()


def load_settings(env_path: Path | None = None) -> Settings:
    """Load Settings from .env (if present) and environment variables.
    
    Also supports Streamlit secrets for cloud deployment.
    """
    if env_path is not None:
        load_dotenv(dotenv_path=env_path, override=False)
    else:
        load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)

    # Try to load from Streamlit secrets if available (for Streamlit Cloud)
    try:
        import streamlit as st
        if hasattr(st, 'secrets'):
            # Streamlit secrets available, use them as fallback
            def get_config(key: str, default: str = "") -> str:
                return os.getenv(key) or st.secrets.get(key, default)
        else:
            get_config = lambda key, default="": os.getenv(key, default)
    except (ImportError, FileNotFoundError):
        # Streamlit not available or no secrets file
        get_config = lambda key, default="": os.getenv(key, default)

    llm_base_url = get_config("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    llm_model = get_config("LLM_MODEL", "qwen2.5:3b").strip()
    llm_api_key = get_config("LLM_API_KEY", "ollama").strip()
    embed_model = get_config("EMBED_MODEL", "nomic-embed-text").strip()
    raw_judge = get_config("JUDGE_MODEL", "").strip()
    judge_model = raw_judge if raw_judge else llm_model
    timeout_seconds = float(get_config("LLM_TIMEOUT_SECONDS", "120"))
    max_retries = int(get_config("LLM_MAX_RETRIES", "3"))
    cache_dir = Path(get_config("FORGEAI_CACHE_DIR", str(PROJECT_ROOT / ".forgeai_cache")))

    return Settings(
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        embed_model=embed_model,
        judge_model=judge_model,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        cache_dir=cache_dir,
    )


def load_prompt(name: str) -> str:
    """Load a plain-text prompt template from forgeai/prompts/<name>.txt."""
    filename = name if name.endswith(".txt") else f"{name}.txt"
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **kwargs: object) -> str:
    """Load and format a prompt template from forgeai/prompts/."""
    template = load_prompt(name)
    return template.format(**kwargs)
