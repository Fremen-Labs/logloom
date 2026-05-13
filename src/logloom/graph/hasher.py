import hashlib
from typing import Optional, Set
from .model import GraphNode

class NodeHasher:
    def __init__(self):
        self._seen_ids: Set[str] = set()

    def generate_node_id(
        self,
        module_path: str,
        class_name: Optional[str],
        function_name: str,
        message_template: str,
        file_path: str,
        parent_scope: str = ""
    ) -> str:
        """Hybrid semantic hashing with collision disambiguation."""
        primary = f"{module_path}:{class_name or ''}.{function_name}:{message_template}"
        base_hash = hashlib.sha256(primary.encode()).hexdigest()[:12]
        base_id = f"ll:{base_hash}"

        if base_id in self._seen_ids:
            # Collision detected: append short context suffix
            context = f"{file_path}:{parent_scope}"
            suffix = hashlib.sha256(context.encode()).hexdigest()[:4]
            final_id = f"{base_id}:{suffix}"
            self._seen_ids.add(final_id)
            return final_id

        self._seen_ids.add(base_id)
        return base_id
