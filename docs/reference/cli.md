# CLI Reference

LogLoom ships with an intuitive, `click`-based command line interface for managing your project's knowledge graph.

## `logloom init`

Initializes LogLoom within the current directory.

**Usage:**
```bash
logloom init [OPTIONS]
```

**Options:**
*   `--force`: Overwrite existing `.logloomrc.toml` and `.logloomignore` files if they are already present.

**Behavior:**
*   Prompts interactively for the project name.
*   Scaffolds default configuration files.

---

## `logloom build`

Scans your repository using the Tree-sitter AST and Regex fallback engines, deterministically hashes node IDs, and generates `logloom-graph.json`.

**Usage:**
```bash
logloom build [OPTIONS]
```

**Options:**
*   `--source PATH`: The directory to scan. Defaults to the current working directory (`.`).
*   `--output PATH`: The destination to write the JSON graph. Defaults to `logloom-graph.json` in the current directory.
*   `--redact-patterns TEXT`: A comma-separated list of substrings to censor. Any log message template containing a match will be scrubbed and replaced with `[REDACTED]`.
*   `--git / --no-git`: Embed git metadata (commit SHA, branch) in the graph metadata (default: `--git`).
*   `--tags / --no-tags`: Run semantic tag auto-inference to categorise log call sites (default: `--tags`).
*   `--call-graph / --no-call-graph`: Resolve inter-function call-graph edges (default: `--call-graph`).
*   `--coverage / --no-coverage`: Compute scan completeness and logging coverage metrics, listing uninstrumented functions (default: `--coverage`).
*   `--languages TEXT`: Comma-separated list of languages to scan. Available options: `python`, `go`, `typescript` (default: `python`).
*   `--name TEXT`: Override project name (defaults to folder name or pyproject.toml value).
*   `--verbose`: Verbose output. Lists all discovered log sites in the terminal during the build.

**Examples:**
```bash
# Basic build targeting the src directory
logloom build --source src/

# Build with sensitive data redaction and coverage metrics
logloom build --source app/ --redact-patterns "password,token,secret" --coverage

# Multi-language scan resolving call-graph and coverage
logloom build --languages python,go,typescript
```
