# ForgeAI - Streamlit Cloud Deployment Guide

## Quick Deploy to Streamlit Cloud

### Prerequisites
- GitHub account
- Streamlit Cloud account (free at https://streamlit.io/cloud)
- Google Gemini API key (get it from https://aistudio.google.com/app/apikey)

### Step 1: Push to GitHub
Your code is already pushed to: https://github.com/adityapratapsingh05/forgeai.git

### Step 2: Deploy to Streamlit Cloud

1. Go to https://share.streamlit.io/
2. Click "New app"
3. Connect your GitHub account if not already connected
4. Select:
   - **Repository:** `adityapratapsingh05/forgeai`
   - **Branch:** `main`
   - **Main file path:** `app/streamlit_app.py`

### Step 3: Configure Secrets

In your Streamlit Cloud app dashboard:

1. Click on your app → **Settings** → **Secrets**
2. Add the following secrets (in TOML format):

```toml
LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
LLM_MODEL = "gemini-2.0-flash-exp"
LLM_API_KEY = "YOUR_ACTUAL_GEMINI_API_KEY_HERE"
EMBED_MODEL = "local:sentence-transformers/all-MiniLM-L6-v2"
JUDGE_MODEL = ""
LLM_TIMEOUT_SECONDS = "120"
LLM_MAX_RETRIES = "3"
FORGEAI_CACHE_DIR = ".forgeai_cache"
```

3. Replace `YOUR_ACTUAL_GEMINI_API_KEY_HERE` with your actual Gemini API key
4. Click **Save**

### Step 4: Deploy

The app will automatically deploy once you save the secrets. If not:
- Click **Reboot** in the app menu

### Troubleshooting

#### ModuleNotFoundError: No module named 'forgeai'
**Solution:** Make sure `setup.py` and `-e .` in `requirements.txt` are present in your repo.

#### API Key Issues
**Solution:** Verify your Gemini API key is correct and has billing enabled if needed.

#### Memory Issues
**Solution:** The free tier has 1GB RAM. Consider:
- Using lighter embedding models
- Reducing document sizes
- Upgrading to Streamlit Cloud paid tier

#### Slow Loading
**Solution:** First load downloads embedding models (~90MB). Subsequent loads are cached.

### Local Testing

Before deploying, test locally:

```bash
# Install the package
pip install -e .

# Set up environment variables
cp .env.example .env
# Edit .env with your API key

# Run locally
streamlit run app/streamlit_app.py
```

### File Structure

```
forgeai/
├── app/
│   └── streamlit_app.py          # Main Streamlit app
├── forgeai/                       # Core package
│   ├── __init__.py
│   ├── agent_runner.py
│   ├── config.py
│   └── ...
├── .streamlit/
│   ├── config.toml                # Streamlit theme config
│   └── secrets.toml.example       # Secrets template
├── setup.py                       # Package setup
├── requirements.txt               # Dependencies
└── README.md                      # Main documentation
```

### Post-Deployment

After successful deployment:

1. Test the **Agent Factory** tab:
   - Upload sample documents
   - Create a test agent
   
2. Test the **Chat Runner** tab:
   - Load a generated agent
   - Ask questions

3. Share your app URL (format: `https://[app-name]-[random-id].streamlit.app`)

### Support

- Streamlit Docs: https://docs.streamlit.io/
- Gemini API Docs: https://ai.google.dev/docs
- Issues: https://github.com/adityapratapsingh05/forgeai/issues

### Cost Considerations

- **Streamlit Cloud Free Tier:** Limited to 1GB RAM, 1 CPU
- **Gemini API:** Has free tier with rate limits
- **Embedding Models:** Downloaded on first run, cached thereafter

### Recommended Settings for Production

For production use, consider:
- Using Streamlit Cloud paid tier for better performance
- Implementing rate limiting
- Adding user authentication
- Monitoring API usage
- Setting up error logging

---

**Happy Deploying! 🚀**
