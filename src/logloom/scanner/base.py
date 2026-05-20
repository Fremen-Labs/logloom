from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

@dataclass(frozen=True)
class LogCallSite:
    file_path: str
    module_path: str
    class_name: Optional[str]
    function_name: str
    log_level: str
    message_template: str
    line: int
    column: int
    lexical_context: dict = None  # Will hold enclosing function, try/except, etc.
    # Phase B: Function signature of the enclosing function.
    # Dict with keys: parameters (list of dicts), return_type (str|None),
    # is_async (bool), decorators (list of str).
    signature: dict = None