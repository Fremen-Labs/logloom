from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class LogCallSite:
    file_path: str
    module_path: str
    class_name: Optional[str] = None
    function_name: str
    log_level: str
    message_template: str
    line_number: int
    column: int
    lexical_context: dict = None  # For Phase 1 lexical parents

class BaseScanner(ABC):
    @abstractmethod
    def scan(self, source_paths: List[str]) -> List[LogCallSite]:
        pass
