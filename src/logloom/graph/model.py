from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import datetime


# ── Phase B: Function signature models ────────────────────────────────────────

class Parameter(BaseModel):
    """A single function parameter with optional type annotation."""
    name: str
    type_hint: Optional[str] = None
    default: Optional[str] = None

class FunctionSignature(BaseModel):
    """The signature of the enclosing function for a log call site.

    Extracted at scan time from the AST of the function_definition (Python),
    function_declaration/method_declaration (Go), or function_declaration/
    arrow_function/method_definition (TypeScript).
    """
    parameters: List[Parameter] = Field(default_factory=list)
    return_type: Optional[str] = None
    is_async: bool = False
    decorators: List[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    """Represents a single log call site in the semantic graph."""
    node_id: str
    file: str
    module: str
    function: str
    level: str
    message_template: str
    line: int
    semantic_tags: List[str] = Field(default_factory=list)
    lexical_parents: List[str] = Field(default_factory=list)
    call_parents: List[str] = Field(default_factory=list)
    call_children: List[str] = Field(default_factory=list)
    # Phase A: Resolved call target names (human-readable, not opaque IDs).
    call_parent_names: List[str] = Field(default_factory=list)
    call_child_names: List[str] = Field(default_factory=list)
    # Phase B: Function signature of the enclosing function.
    signature: Optional[FunctionSignature] = None

class CoverageMetrics(BaseModel):
    """Scan completeness and code-base logging coverage metrics."""
    total_functions: int
    instrumented_functions: int
    coverage_pct: float
    uninstrumented: List[str] = Field(default_factory=list)


class ModelField(BaseModel):
    """Represents a field in a model definition."""
    name: str
    type_hint: Optional[str] = None
    default: Optional[str] = None


class ModelDefinition(BaseModel):
    """Represents a scanned data model (e.g. class, struct, interface)."""
    name: str
    file: str
    line: int
    base_classes: List[str] = Field(default_factory=list)
    fields: List[ModelField] = Field(default_factory=list)


class LogLoomGraph(BaseModel):
    """The full knowledge graph artifact."""
    schema_version: str = "2.0"
    project: str
    built_at: str
    commit_sha: Optional[str] = None
    branch: Optional[str] = None
    nodes: Dict[str, GraphNode]
    redacted_patterns: List[str] = Field(default_factory=list)
    coverage: Optional[CoverageMetrics] = None
    models: Dict[str, ModelDefinition] = Field(default_factory=dict)
    imports: Dict[str, List[str]] = Field(default_factory=dict)

    def save(self, path: str):
        with open(path, "w") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str) -> "LogLoomGraph":
        with open(path) as f:
            data = f.read()
        return cls.model_validate_json(data)
