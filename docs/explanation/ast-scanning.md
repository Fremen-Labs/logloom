# How AST Scanning Works

LogLoom utilizes a two-tier extraction engine to map your codebase at build time. This ensures 100% recall of your log statements without slowing down your runtime performance.

## Tier 1: Tree-sitter AST (High Precision)

LogLoom’s primary engine uses [Tree-sitter](https://tree-sitter.github.io/tree-sitter/), a modern, incremental parsing system used by GitHub and modern IDEs. 

1. **Query Execution**: We run a `.scm` query against the parsed Python syntax tree, specifically targeting `logger.info`, `logging.error`, and `self.log` patterns.
2. **Robust Extraction**: If you write `logger.info(f"User {user_id} login")`, Tree-sitter doesn't just see a string. It sees an `interpolation` node (`{user_id}`) embedded inside `string_content`. LogLoom intelligently extracts this and converts the dynamic code into a canonical template: `"User {} login"`.
3. **Lexical Context**: The scanner "walks up" the syntax tree from the log call to discover the enclosing function, class, and block scope (e.g. `try/except`), binding this topological context directly to the log node.

## Tier 2: Regex Fallback (High Recall)

Sometimes, highly dynamic meta-programming or obscured logging wrappers defeat the strict AST query. To ensure no log line is left behind, LogLoom immediately follows the AST pass with a Regex sweep.

1. **Multiline Detection**: A robust multiline regex scans for fallback log patterns.
2. **Deduplication**: The `GraphBuilder` engine merges the findings, giving strict priority to the AST nodes (matching via exact file path and line number).

By combining High Precision (AST) and High Recall (Regex), LogLoom guarantees an exhaustively mapped execution graph.
