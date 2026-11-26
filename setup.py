"""Setup configuration for ForgeAI."""

from setuptools import setup, find_packages

setup(
    name="forgeai",
    version="0.1.0",
    description="ForgeAI - Automated Agent Factory with Document Grounding",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "pydantic>=2.6.0",
        "pyyaml>=6.0.1",
        "httpx>=0.27.0",
        "requests>=2.31.0",
        "rank_bm25>=0.2.2",
        "numpy>=1.26.0",
        "pypdf>=4.0.0",
        "pandas>=2.1.0",
        "rich>=13.7.0",
        "typer>=0.12.0",
        "streamlit>=1.35.0",
        "pytest>=8.0.0",
        "python-dotenv>=1.0.1",
        "fastembed>=0.7.3,<0.8",
    ],
    include_package_data=True,
    package_data={
        "forgeai": ["prompts/*.txt"],
    },
)
