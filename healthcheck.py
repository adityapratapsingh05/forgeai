#!/usr/bin/env python3
"""Health check script for ForgeAI deployment."""

import sys
from pathlib import Path


def check_imports():
    """Check if all required packages can be imported."""
    print("🔍 Checking Python imports...")
    required_imports = [
        "pydantic",
        "yaml",
        "httpx",
        "requests",
        "rank_bm25",
        "numpy",
        "pypdf",
        "pandas",
        "rich",
        "typer",
        "streamlit",
        "dotenv",
        "fastembed",
    ]
    
    failed = []
    for module in required_imports:
        try:
            __import__(module)
            print(f"  ✅ {module}")
        except ImportError as e:
            print(f"  ❌ {module} - {e}")
            failed.append(module)
    
    return len(failed) == 0


def check_forgeai_package():
    """Check if forgeai package is importable."""
    print("\n🔍 Checking forgeai package...")
    try:
        from forgeai import __version__
        from forgeai.config import load_settings
        from forgeai.llm import LLMClient
        from forgeai.agent_runner import AgentRunner
        print(f"  ✅ forgeai package (v{__version__})")
        print("  ✅ All core modules accessible")
        return True
    except ImportError as e:
        print(f"  ❌ forgeai package not found: {e}")
        print("\n  💡 Solution: Run 'pip install -e .' from the project root")
        return False


def check_config():
    """Check if configuration is set up."""
    print("\n🔍 Checking configuration...")
    try:
        from forgeai.config import load_settings
        settings = load_settings()
        
        print(f"  ✅ Configuration loaded")
        print(f"     - Model: {settings.llm_model}")
        print(f"     - Base URL: {settings.llm_base_url}")
        print(f"     - Embed Model: {settings.embed_model}")
        
        if settings.llm_api_key == "ollama" or settings.llm_api_key == "replace-with-your-gemini-api-key":
            print("  ⚠️  API key not set (using default)")
            return False
        else:
            print(f"  ✅ API key configured ({settings.llm_api_key[:8]}...)")
        
        return True
    except Exception as e:
        print(f"  ❌ Configuration error: {e}")
        return False


def check_directories():
    """Check required directories exist."""
    print("\n🔍 Checking directories...")
    required_dirs = [
        "forgeai",
        "forgeai/prompts",
        "app",
        "demos",
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        path = Path(dir_path)
        if path.exists():
            print(f"  ✅ {dir_path}")
        else:
            print(f"  ❌ {dir_path} not found")
            all_exist = False
    
    return all_exist


def check_streamlit():
    """Check if Streamlit app can be loaded."""
    print("\n🔍 Checking Streamlit app...")
    app_path = Path("app/streamlit_app.py")
    
    if not app_path.exists():
        print("  ❌ streamlit_app.py not found")
        return False
    
    print("  ✅ streamlit_app.py exists")
    
    # Try to import the app without running it
    try:
        import ast
        with open(app_path, 'r', encoding='utf-8') as f:
            ast.parse(f.read())
        print("  ✅ streamlit_app.py syntax valid")
        return True
    except SyntaxError as e:
        print(f"  ❌ Syntax error in streamlit_app.py: {e}")
        return False


def main():
    """Run all health checks."""
    print("=" * 60)
    print("🏥 ForgeAI Health Check")
    print("=" * 60)
    
    checks = [
        ("Imports", check_imports),
        ("ForgeAI Package", check_forgeai_package),
        ("Configuration", check_config),
        ("Directories", check_directories),
        ("Streamlit App", check_streamlit),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Unexpected error in {name}: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("📊 Summary")
    print("=" * 60)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
    
    all_passed = all(result for _, result in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All checks passed! Ready to deploy.")
        print("\n🚀 Next steps:")
        print("   1. Test locally: streamlit run app/streamlit_app.py")
        print("   2. Deploy to Streamlit Cloud: https://share.streamlit.io/")
        return 0
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        print("\n💡 Common fixes:")
        print("   - Install package: pip install -e .")
        print("   - Install dependencies: pip install -r requirements.txt")
        print("   - Set up .env file with your API key")
        return 1


if __name__ == "__main__":
    sys.exit(main())
