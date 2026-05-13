# LogLoom

**Weave your codebase into every log line.**

Turn plain logs into a queryable execution graph with zero developer friction.  
AST-powered semantic provenance for humans, agents, and Elasticsearch.

## Features

- Build-time AST scanning → semantic knowledge graph
- Runtime logs carry tiny, stable node IDs
- Human-readable logs remain completely unchanged
- Instant causal reasoning in Elasticsearch + AI agents
- Drop-in wrapper for structlog, logging, etc.

## Quick Start

```bash
pip install logloom
```

```python
# In CI / build step
logloom build --source .

# In your code - exactly like a normal logger
from logloom import get_logger
logger = get_logger(__name__)

logger.info("User login failed", user_id=123, reason="token_expired")
```

## Project Status
Early prototype — Python first, multi-language (via Tree-sitter) coming soon.

## License
MIT