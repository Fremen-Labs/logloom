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

# In CI / build step
logloom build --source .

# In your code - exactly like a normal logger
from logloom import get_logger
logger = get_logger(__name__)

logger.info("User login failed", user_id=123, reason="token_expired")

# Project Status

Early prototype — Python first, multi-language (via Tree-sitter) coming soon.

# License

MIT


### 2. `LICENSE`
```text
MIT License

Copyright (c) 2026 Fremen Labs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

