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

See the full [architecture](ARCHITECTURE.md) and roadmap in the repo.

## License
MIT
