import hashlib
from typing import Optional

def generate_node_id(
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

    # Simple collision detection (in practice, track seen in builder)
    # For now, always include short context suffix for safety
    context = f"{file_path}:{parent_scope}"
    suffix = hashlib.sha256(context.encode()).hexdigest()[:4]
    return f"{base_id}:{suffix}" if suffix else base_id
