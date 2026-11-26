# ForgeAI Deployment Guide

> **Status:** This guide contains deployment examples, not a verified production
> deployment. The Streamlit app has no built-in authentication; do not expose it
> publicly without adding and testing an access-control layer. Ollama is optional:
> configure `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, and `EMBED_MODEL` for an
> OpenAI-compatible chat provider such as Gemini. With `EMBED_MODEL=local:...`,
> FastEmbed runs the embedding model inside the app container.

## Deployment Templates (Not Production-Verified)

### Option 1: Docker Deployment Example

#### Create Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose Streamlit port
EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Run Streamlit
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

#### Create docker-compose.yml

```yaml
services:
  forgeai:
    build: .
    ports:
      - "8501:8501"
    env_file:
      - .env
    volumes:
      - ./runs:/app/runs
      - ./demos:/app/demos
      - ./.forgeai_cache:/app/.forgeai_cache
    restart: unless-stopped
```

#### Deploy with Docker
```bash
# Create .env with your API provider settings first; do not commit it.
cp .env.example .env
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f forgeai

# Access at http://localhost:8501
```

### Option 2: Cloud API Deployment (Faster)

Configure an OpenAI-compatible chat provider. Gemini is the documented default;
model IDs and account quotas can change, so confirm them before large runs.

#### Update .env
```bash
# Using Gemini
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-3.1-flash-lite
LLM_API_KEY=your-gemini-api-key
EMBED_MODEL=local:sentence-transformers/all-MiniLM-L6-v2

# Or use OpenAI's compatible chat and embeddings APIs
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=your-current-chat-model
LLM_API_KEY=your-openai-api-key
EMBED_MODEL=text-embedding-3-small
```

#### Deploy to Cloud Platform

**Streamlit Cloud:**
```bash
# 1. Push to GitHub
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/yourusername/forgeai.git
git push -u origin main

# 2. Go to share.streamlit.io
# 3. Connect GitHub repo
# 4. Add secrets in Streamlit dashboard:
#    - LLM_BASE_URL
#    - LLM_MODEL
#    - LLM_API_KEY
#    - EMBED_MODEL
```

**Heroku:**
```bash
# Create Procfile
echo "web: streamlit run app/streamlit_app.py --server.port=\$PORT --server.address=0.0.0.0" > Procfile

# Deploy
heroku create your-forgeai-app
heroku config:set LLM_BASE_URL=your-url
heroku config:set LLM_API_KEY=your-key
git push heroku main
```

**AWS ECS / Google Cloud Run:**
```bash
# Build and push Docker image
docker build -t forgeai:latest .
docker tag forgeai:latest gcr.io/your-project/forgeai:latest
docker push gcr.io/your-project/forgeai:latest

# Deploy via Cloud Run
gcloud run deploy forgeai \
  --image gcr.io/your-project/forgeai:latest \
  --platform managed \
  --region us-central1 \
  --no-allow-unauthenticated \
  --set-env-vars="LLM_BASE_URL=your-url,LLM_API_KEY=your-key"
```

### Option 3: Local Production Setup

For on-premise deployment with GPU acceleration:

```bash
# 1. Install CUDA-enabled PyTorch
pip install torch --index-url https://download.pytorch.org/whl/cu118

# 2. Use local Ollama with GPU
# Edit .env:
LLM_MODEL=qwen2.5:14b  # Larger model for better quality
JUDGE_MODEL=qwen2.5:32b  # Separate stronger judge

# 3. Run as systemd service
sudo tee /etc/systemd/system/forgeai.service > /dev/null <<EOF
[Unit]
Description=ForgeAI Streamlit Service
After=network.target ollama.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/path/to/forgeai
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/local/bin/streamlit run app/streamlit_app.py --server.port=8501
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable forgeai
sudo systemctl start forgeai
```

## 🔒 Security Considerations

### API Keys
```bash
# Keep credentials and local caches out of version control.
# The repository .gitignore already excludes .env and .forgeai_cache/.
# Do not ignore runs/ when preparing the assignment: generated run artifacts
# are required evidence and should be reviewed before committing.

# Use environment variables in production
export LLM_API_KEY=$(aws secretsmanager get-secret-value --secret-id forgeai-llm-key --query SecretString --output text)
```

### Authentication
Add authentication to Streamlit:

```python
# Add to app/streamlit_app.py
import streamlit_authenticator as stauth

authenticator = stauth.Authenticate(
    credentials,
    'forgeai_auth',
    'forgeai_key',
    cookie_expiry_days=30
)

name, authentication_status, username = authenticator.login('Login', 'main')

if authentication_status:
    # Show app
    pass
elif authentication_status == False:
    st.error('Username/password is incorrect')
elif authentication_status == None:
    st.warning('Please enter your username and password')
```

### Rate Limiting
```python
# Add to agent_runner.py
from ratelimit import limits, sleep_and_retry

@sleep_and_retry
@limits(calls=10, period=60)  # 10 requests per minute
def ask(self, query: str):
    # existing implementation
```

## 📊 Monitoring & Logging

### Add Logging
```python
# Add to config.py
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('forgeai.log'),
        logging.StreamHandler()
    ]
)
```

### Track Metrics
```python
# Add to agent_runner.py
import time
from prometheus_client import Counter, Histogram

query_counter = Counter('forgeai_queries_total', 'Total queries processed')
query_duration = Histogram('forgeai_query_duration_seconds', 'Query processing time')

def ask(self, query: str):
    query_counter.inc()
    with query_duration.time():
        # existing implementation
```

## 🔄 CI/CD Pipeline

### GitHub Actions
```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python -m pytest -v
```

### Auto-deploy on push
```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: docker/build-push-action@v4
        with:
          push: true
          tags: user/forgeai:latest
      - run: |
          gcloud run deploy forgeai \
            --image user/forgeai:latest \
            --region us-central1
```

## 📈 Scaling

### Horizontal Scaling
```bash
# Multiple Streamlit instances behind load balancer
# nginx.conf
upstream forgeai {
    least_conn;
    server forgeai1:8501;
    server forgeai2:8501;
    server forgeai3:8501;
}

server {
    listen 80;
    location / {
        proxy_pass http://forgeai;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Caching
```python
# Add Redis caching for retrieval results
import redis
import pickle

redis_client = redis.Redis(host='localhost', port=6379)

def retrieve_with_cache(self, query: str):
    cache_key = f"retrieve:{hash(query)}"
    cached = redis_client.get(cache_key)
    if cached:
        return pickle.loads(cached)
    
    results = self._retrieve(query)
    redis_client.setex(cache_key, 3600, pickle.dumps(results))
    return results
```

## 🎯 Performance Optimization

### Use Faster Models
- **vLLM** for faster inference: https://github.com/vllm-project/vllm
- **llama.cpp** for CPU optimization: https://github.com/ggerganov/llama.cpp
- **TensorRT-LLM** for NVIDIA GPUs

### Batch Processing
```python
# Process multiple queries in parallel
from concurrent.futures import ThreadPoolExecutor

def batch_ask(self, queries: list[str]):
    with ThreadPoolExecutor(max_workers=4) as executor:
        return list(executor.map(self.ask, queries))
```

## 📞 Support

For production deployment issues:
1. Check logs: `docker-compose logs -f`
2. Verify the configured provider, model IDs, and API key
3. Check connectivity to the configured OpenAI-compatible API endpoint
4. Review metrics: Check Prometheus/Grafana dashboards

## ✅ Pre-deployment Checklist

- [ ] All tests passing
- [ ] API keys in environment variables (not .env)
- [ ] Rate limiting configured
- [ ] Logging enabled
- [ ] Monitoring setup (Prometheus/Datadog/etc)
- [ ] Backups configured for runs/ directory
- [ ] SSL/TLS certificates installed
- [ ] Authentication enabled for public deployments
- [ ] Health checks configured
- [ ] Auto-restart on failure
- [ ] Resource limits set (CPU/memory)
- [ ] Documentation updated with deployment URL
