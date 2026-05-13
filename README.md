# LogLoom

**Weave your codebase into every log line.**

Turn plain logs into a queryable execution graph with zero developer friction.  
AST-powered semantic provenance for humans, agents, and Elasticsearch.

## Quick Start

```bash
pip install logloom
```

```python
# In CI / build step
logloom build --source .

# In your code
from logloom import get_logger
logger = get_logger(__name__)

logger.info("User login failed", user_id=123, reason="token_expired")
```

### The Knowledge Graph (`logloom-graph.json`)
At build time, `logloom build` generates a semantic graph map of your code:
```json
{
  "nodes": {
    "ll:abc123def456": {
      "file": "src/auth.py",
      "module": "app.auth",
      "function": "authenticate",
      "message_template": "User login failed",
      "lexical_parents": ["AuthService", "try_except"]
    }
  }
}
```

### Enriched Runtime Output
At runtime, the `get_logger()` wrapper resolves the exact line of code to its `ll:` node ID, appending it as `ll_node`.

```json
{
  "event": "User login failed",
  "user_id": 123,
  "reason": "token_expired",
  "ll_node": "ll:abc123def456",
  "ll_module": "app.auth",
  "ll_function": "authenticate"
}
```

See the full [architecture](ARCHITECTURE.md) and roadmap in the repo.

## License
MIT
