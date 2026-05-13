from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import datetime

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

class LogLoomGraph(BaseModel):
    """The full knowledge graph artifact."""
    schema_version: str = "1"
    project: str
    built_at: str
    commit_sha: Optional[str] = None
    branch: Optional[str] = None
    nodes: Dict[str, GraphNode]
    redacted_patterns: List[str] = Field(default_factory=list)

    def save(self, path: str):
        with open(path, "w") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str) -> "LogLoomGraph":
        with open(path) as f:
            data = f.read()
        return cls.model_validate_json(data)
