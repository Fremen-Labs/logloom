"""Issue #19 — Graph diff.

Compares two LogLoomGraph versions and reports added, removed, moved,
and modified log sites. Useful in CI to detect regressions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..graph.model import GraphNode, LogLoomGraph


@dataclass
class NodeChange:
    """Describes a single change between two graph versions."""
    node_id: str
    change_type: str   # "added", "removed", "moved", "modified"
    old_node: Optional[GraphNode] = None
    new_node: Optional[GraphNode] = None
    details: str = ""


@dataclass
class GraphDiff:
    """Full diff result between two graph versions."""
    old_version: str
    new_version: str
    added: List[NodeChange] = field(default_factory=list)
    removed: List[NodeChange] = field(default_factory=list)
    moved: List[NodeChange] = field(default_factory=list)
    modified: List[NodeChange] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.moved) + len(self.modified)

    @property
    def has_changes(self) -> bool:
        return self.total_changes > 0

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"+{len(self.added)} added")
        if self.removed:
            parts.append(f"-{len(self.removed)} removed")
        if self.moved:
            parts.append(f"~{len(self.moved)} moved")
        if self.modified:
            parts.append(f"Δ{len(self.modified)} modified")
        if not parts:
            return "No changes"
        return ", ".join(parts)


def diff_graphs(old: LogLoomGraph, new: LogLoomGraph) -> GraphDiff:
    """Compute the diff between two LogLoomGraph versions.

    Detection strategy:
    - Added:    node_id exists in new but not old
    - Removed:  node_id exists in old but not new
    - Moved:    same node_id, different file or line
    - Modified: same node_id, different message_template, level, or tags
    """
    result = GraphDiff(
        old_version=old.built_at,
        new_version=new.built_at,
    )

    old_ids = set(old.nodes.keys())
    new_ids = set(new.nodes.keys())

    # ── Pure additions ────────────────────────────────────────────────────
    for nid in new_ids - old_ids:
        node = new.nodes[nid]
        result.added.append(NodeChange(
            node_id=nid,
            change_type="added",
            new_node=node,
            details=f"{node.file}:{node.line} {node.function}() → \"{node.message_template}\"",
        ))

    # ── Pure removals ─────────────────────────────────────────────────────
    for nid in old_ids - new_ids:
        node = old.nodes[nid]
        result.removed.append(NodeChange(
            node_id=nid,
            change_type="removed",
            old_node=node,
            details=f"{node.file}:{node.line} {node.function}() → \"{node.message_template}\"",
        ))

    # ── Shared IDs: check for moves or modifications ─────────────────────
    for nid in old_ids & new_ids:
        old_node = old.nodes[nid]
        new_node = new.nodes[nid]

        # Moved: same ID but different location
        if old_node.file != new_node.file or old_node.line != new_node.line:
            result.moved.append(NodeChange(
                node_id=nid,
                change_type="moved",
                old_node=old_node,
                new_node=new_node,
                details=(
                    f"{old_node.file}:{old_node.line} → "
                    f"{new_node.file}:{new_node.line}"
                ),
            ))
        # Modified: same location but different content
        elif (
            old_node.message_template != new_node.message_template
            or old_node.level != new_node.level
            or old_node.semantic_tags != new_node.semantic_tags
        ):
            changes = []
            if old_node.message_template != new_node.message_template:
                changes.append(f"message: \"{old_node.message_template}\" → \"{new_node.message_template}\"")
            if old_node.level != new_node.level:
                changes.append(f"level: {old_node.level} → {new_node.level}")
            if old_node.semantic_tags != new_node.semantic_tags:
                changes.append(f"tags: {old_node.semantic_tags} → {new_node.semantic_tags}")

            result.modified.append(NodeChange(
                node_id=nid,
                change_type="modified",
                old_node=old_node,
                new_node=new_node,
                details="; ".join(changes),
            ))

    return result
