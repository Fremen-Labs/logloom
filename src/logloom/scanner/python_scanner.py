import tree_sitter_python as tspython
from tree_sitter import Language, Parser
from pathlib import Path
from typing import List
from .base import LogCallSite
from .queries.python_logs import PYTHON_LOGS_QUERY

class PythonScanner:
    def __init__(self):
        self.language = Language(tspython.language())
        self.parser = Parser()
        self.parser.set_language(self.language)
        self.query = self.language.query(PYTHON_LOGS_QUERY)

    def scan_file(self, file_path: Path) -> List[LogCallSite]:
        if not file_path.suffix == ".py":
            return []
        
        with open(file_path, "rb") as f:
            source = f.read()

        tree = self.parser.parse(source)
        captures = self.query.captures(tree.root_node)

        sites = []
        for node, tag in captures:
            if tag == "log_call" or tag == "log_call_module":
                # Find the level
                level_node = None
                for child in node.child_by_field_name("function").children:
                    if child.type == "identifier":
                        level_node = child
                
                level = level_node.text.decode("utf-8") if level_node else "info"

                # Extract message from @first_arg
                # We need to find the node tagged as @first_arg in this capture match
                # captures returns (node, tag), so if we are at log_call, the @first_arg is a different capture.
                # Actually, the python_logs.scm assigns @first_arg to the first argument.
                # Let's iterate over captures and group them by the main log_call node.
                pass

        # Since Tree-sitter captures are flattened, a better approach is to group them
        # Let's refactor to process query matches
        matches = self.query.matches(tree.root_node)
        
        for match in matches:
            # match is a tuple: (pattern_index, dict_of_captures)
            # Actually, `query.matches` returns a list of tuples: (pattern_index, dict_mapping_tag_to_nodes)
            # In tree-sitter python bindings (v0.23+), `query.matches` yields (pattern_index, capture_dict) where capture_dict maps string names to lists of Nodes
            captures_dict = match[1]
            
            log_method_nodes = captures_dict.get("log_method", [])
            first_arg_nodes = captures_dict.get("first_arg", [])
            
            if not log_method_nodes or not first_arg_nodes:
                continue
                
            log_method_node = log_method_nodes[0]
            first_arg_node = first_arg_nodes[0]
            
            level = log_method_node.text.decode("utf-8")
            
            # Extract string content from first_arg_node
            message = self._extract_string(first_arg_node, source)
            
            # Find enclosing function
            parent = log_method_node.parent
            enclosing_func = None
            in_try_except = False
            
            while parent:
                if parent.type == "function_definition":
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        enclosing_func = name_node.text.decode("utf-8")
                        break
                if parent.type == "try_statement":
                    in_try_except = True
                parent = parent.parent

            # Extract class name if inside a class
            class_name = None
            if parent:
                class_parent = parent.parent
                while class_parent:
                    if class_parent.type == "class_definition":
                        name_node = class_parent.child_by_field_name("name")
                        if name_node:
                            class_name = name_node.text.decode("utf-8")
                            break
                    class_parent = class_parent.parent

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
                    "in_try_except": in_try_except
                }
            ))

        return sites

    def _extract_string(self, node, source: bytes) -> str:
        """Extract literal text from a string or f-string node."""
        if node.type == "string":
            # Just extract the text and strip quotes
            text = node.text.decode("utf-8")
            if text.startswith('f"') or text.startswith("f'"):
                return text[2:-1]
            elif text.startswith('"') or text.startswith("'"):
                return text[1:-1]
            return text
        # If it's a binary expression like "a" + "b", we can just return the raw source
        return node.text.decode("utf-8").strip("\"'")

    def _get_module_path(self, file_path: Path) -> str:
        parts = list(file_path.with_suffix("").parts)
        if "src" in parts:
            idx = parts.index("src")
            return ".".join(parts[idx+1:])
        return ".".join(parts[-3:])