# Tutorial: Getting Started with LogLoom

LogLoom is an intelligent logging wrapper that statically maps your codebase at build time so your logs have rich, O(1) runtime context.

This tutorial will guide you through initializing LogLoom, building your first knowledge graph, and capturing enriched runtime logs.

## 1. Installation

Install LogLoom directly from pip. (For development, use the `[dev]` flag).

```bash
pip install logloom
```

## 2. Initialization

Navigate to the root of your Python project and run the init command. This scaffolds the baseline configuration files.

```bash
logloom init
```

* You will be prompted for a project name.
* This command generates `.logloomignore` (to ignore `__pycache__` and virtual environments) and `.logloomrc.toml`.

## 3. Write Some Code

Create a simple Python script `src/app.py` utilizing the LogLoom wrapper:

```python
from logloom import get_logger

# get_logger() perfectly mirrors standard structlog
logger = get_logger(__name__)

def process_payment(user_id: int):
    try:
        logger.info(f"Processing payment for user {user_id}")
    except Exception:
        logger.exception("Payment failed completely")

process_payment(42)
```

## 4. Build the Graph

Before you run your code (or during your CI/CD pipeline), build the knowledge graph. The scanner will read your Python files using an AST (Abstract Syntax Tree) to map the log lines.

```bash
logloom build --source src/
```

This generates a `logloom-graph.json` file at the root of your repository. If you open it, you will see your log templates cleanly extracted (e.g. `"Processing payment for user {}"`), assigned a unique `ll:abc123def456` ID, and mapped to the `process_payment` function scope.

## 5. Run Your Application

Execute your script:

```bash
python src/app.py
```

Because the graph is present, LogLoom's zero-overhead `sys._getframe()` lookup will instantly map the executing line to the semantic graph node. Your standard out will now include powerful metadata:

```json
{
    "event": "Processing payment for user 42",
    "ll_node": "ll:abc123def456",
    "ll_module": "app",
    "ll_function": "process_payment"
}
```

**Next Steps**: Check out the [How to Redact Sensitive Data](../how-to/redact-sensitive-data.md) guide to protect PII.
