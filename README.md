**✅ README Review + Uplift Delivered**

The current README is clean, functional, and already better than most early-stage projects. It has the essentials: tagline, quick start, graph example, and output sample.

### Uplifted Version (with 90s Flair + Levity)

Here's the full recommended replacement for `README.md`. It keeps everything **grounded in real engineering** (no hype, clear constraints, practical focus) while adding that retro 90s cyber-vibe and light humor.

```markdown
# LogLoom

**Weave your codebase into every log line.**  
*Like a 90s BBS sysop who actually knew where the packets were dropping.*

Turn flat, boring logs into a **queryable execution graph** with zero developer friction.  
Build-time AST magic meets runtime enlightenment — perfect for humans, agentic debuggers, and Elasticsearch wranglers alike.

## Why LogLoom? (The Real Talk)

Modern logs are like 90s AOL chat: humans can read them, but good luck getting an AI to understand the *intent* behind the code.  

LogLoom fixes that by:
- Scanning your source **at build time** (Tree-sitter powered — no runtime tax)
- Building a stable semantic knowledge graph
- Injecting tiny, permanent `ll:` node references into every log line
- Giving Elasticsearch + AI agents instant causal superpowers

All while your human logs stay clean. No more "where the heck was this log called?" detective work at 3am.

## Quick Start (Dial-up Fast)

```bash
pip install logloom
```

```python
# 1. In CI / build pipeline (do this once per deploy)
logloom build --source .

# 2. In your code — works exactly like structlog or logging
from logloom import get_logger

logger = get_logger(__name__)

logger.info("User login failed", user_id=123, reason="token_expired")
```

That’s it. Your logs now carry the DNA of the code that wrote them.

## What Actually Happens Under the Hood

### Build Time (`logloom build`)
Creates `logloom-graph.json` — your app’s **living source map**:

```json
{
  "nodes": {
    "ll:abc123def456": {
      "file": "src/auth/service.py",
      "module": "app.auth.service",
      "function": "authenticate",
      "message_template": "User login failed",
      "lexical_parents": ["try:refresh_token", "AuthService"],
      "semantic_tags": ["auth", "security"]
    }
  }
}
```

### Runtime Output (Enriched but Still Human-Friendly)

```json
{
  "event": "User login failed",
  "user_id": 123,
  "reason": "token_expired",
  "ll_node": "ll:abc123def456",
  "ll_module": "app.auth.service",
  "ll_function": "authenticate",
  "ll_tags": ["auth", "security"]
}
```

Now your Elastic queries and AI agents can say things like:  
*"Show me every failure in the auth retry path in the last hour"*  
and actually get meaningful answers.

## Features (No Marketing Fluff)

- **Zero runtime overhead** when graph is missing (graceful fallback)
- **Stable node IDs** that survive refactors
- **Redaction support** (`--redact-patterns "password,token"`)
- Works great with structlog (and stdlib logging via wrapper)
- Designed from day one for Elasticsearch + OpenTelemetry
- Multi-language ready (Python first, Go/TS coming)

## Installation

```bash
# For normal use
pip install logloom

# For building graphs
pip install "logloom[build]"
```

## Next Level Stuff

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical deep dive and [roadmap](https://github.com/Fremen-Labs/logloom/issues) for what’s coming (semantic tags, `logloom graph` explorer, linting, etc.).

---

**License**  
MIT — because sharing is caring, even in the 90s.

---
