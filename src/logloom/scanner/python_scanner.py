import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor
from pathlib import Path
from typing import List, Optional
from .base import LogCallSite
from .queries.python_logs import PYTHON_LOGS_QUERY

class PythonScanner:
    def __init__(self):
        self.language = Language(tspython.language())
        self.parser = Parser(self.language)
        self.query = Query(self.language, PYTHON_LOGS_QUERY)

    def scan_file(self, file_path: Path) -> List[LogCallSite]:
        if not file_path.suffix == ".py":
            return []
        
        with open(file_path, "rb") as f:
            source = f.read()

        tree = self.parser.parse(source)
        cursor = QueryCursor(self.query)
        matches = cursor.matches(tree.root_node)

        sites = []
        for match in matches:
            # match is (pattern_index, dict_mapping_tag_to_nodes)
            captures_dict = match[1]
            
            log_method_nodes = captures_dict.get("log_method", [])
            first_arg_nodes = captures_dict.get("first_arg", [])
            
            if not log_method_nodes or not first_arg_nodes:
                continue
                
            log_method_node = log_method_nodes[0]
            first_arg_node = first_arg_nodes[0]
            
            level = log_method_node.text.decode("utf-8")
            
            # Extract string content from first_arg_node (handling f-strings and concats)
            message = self._extract_string(first_arg_node, source)
            
            # Lexical context traversal
            enclosing_func, class_name, in_try, in_if, in_loop, decorators = self._get_lexical_context(log_method_node)

            sites.append(LogCallSite(
                file_path=str(file_path),
                module_path=self._get_module_path(file_path),
                class_name=class_name,
                function_name=enclosing_func or "<module>",
                log_level=level,
                message_template=message,
                line=log_method_node.start_point.row + 1,
                column=log_method_node.start_point.column,
                lexical_context={
                    "enclosing_function": enclosing_func,
                    "in_try_except": in_try,
                    "in_if_block": in_if,
                    "in_loop": in_loop,
                    "decorators": decorators
                }
            ))

        return sites

    def _extract_string(self, node, source: bytes) -> str:
        """Robustly extract a message template from a string, f-string, or binary concat."""
        if node.type == "string":
            # For standard strings, we can just strip quotes.
            # But tree-sitter parses f-strings as a string containing:
            # string_start, string_content, interpolation, string_end
            parts = []
            has_interpolation = False
            for child in node.children:
                if child.type == "string_content":
                    parts.append(child.text.decode("utf-8"))
                elif child.type == "interpolation":
                    parts.append("{}")
                    has_interpolation = True
            
            if has_interpolation or parts:
                return "".join(parts)
            
            # Fallback for plain strings without child nodes in older parser versions
            text = node.text.decode("utf-8")
            if text.startswith('f"') or text.startswith("f'") or text.startswith('r"') or text.startswith("r'"):
                return text[2:-1]
            elif text.startswith('"') or text.startswith("'"):
                return text[1:-1]
            return text

        if node.type == "binary_operator":
            # Very simplistic concat handling: left + right
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left and right:
                return self._extract_string(left, source) + self._extract_string(right, source)

        # Fallback to raw text, stripping common quotes just in case
        text = node.text.decode("utf-8")
        if text.startswith('f"') or text.startswith("f'"):
            return text[2:-1]
        elif text.startswith('"') or text.startswith("'"):
            return text[1:-1]
        return text

    def _get_lexical_context(self, node):
        enclosing_func = None
        class_name = None
        in_try = False
        in_if = False
        in_loop = False
        decorators = []
        
        parent = node.parent
        while parent:
            if parent.type == "function_definition":
                if not enclosing_func: # Only grab the innermost function
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        enclosing_func = name_node.text.decode("utf-8")
                    
                    # Grab decorators if any
                    for child in parent.children:
                        if child.type == "decorator":
                            decorators.append(child.text.decode("utf-8").lstrip("@"))
            
            elif parent.type == "class_definition":
                if not class_name: # Innermost class
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        class_name = name_node.text.decode("utf-8")
            
            elif parent.type == "try_statement":
                in_try = True
            elif parent.type == "if_statement":
                in_if = True
            elif parent.type in ["for_statement", "while_statement"]:
                in_loop = True
                
            parent = parent.parent
            
        return enclosing_func, class_name, in_try, in_if, in_loop, decorators

    def _get_module_path(self, file_path: Path) -> str:
        parts = list(file_path.with_suffix("").parts)
        if "src" in parts:
            idx = parts.index("src")
            return ".".join(parts[idx+1:])
        return ".".join(parts[-3:])