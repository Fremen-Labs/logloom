"""Scanner submodule to extract data model definitions (Pydantic, structs, interfaces)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List
from ..graph.model import ModelDefinition, ModelField

try:
    from tree_sitter import Language, Parser, Query
    try:
        from tree_sitter import QueryCursor
    except ImportError:
        QueryCursor = None
except ImportError:
    Language = None
    Parser = None
    Query = None
    QueryCursor = None

logger = logging.getLogger(__name__)

_PYTHON_EXTS = {".py"}
_GO_EXTS = {".go"}
_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def scan_models(source_paths: List[Path], languages: List[str]) -> Dict[str, ModelDefinition]:
    """Scan all source files for data model definitions."""
    if Parser is None:
        return {}

    all_files: List[Path] = []
    for path in source_paths:
        if path.is_file():
            all_files.append(path)
        elif path.is_dir():
            all_files.extend(path.rglob("*"))

    models: Dict[str, ModelDefinition] = {}

    for f in all_files:
        suffix = f.suffix
        if suffix in _PYTHON_EXTS and "python" in languages:
            try:
                for model in _extract_python_models(f):
                    models[model.name] = model
            except Exception as e:
                logger.debug(f"Failed to extract Python models from {f}: {e}")

        elif suffix in _GO_EXTS and "go" in languages:
            if f.name.endswith("_test.go"):
                continue
            try:
                for model in _extract_go_models(f):
                    models[model.name] = model
            except Exception as e:
                logger.debug(f"Failed to extract Go models from {f}: {e}")

        elif suffix in _TS_EXTS and "typescript" in languages:
            try:
                for model in _extract_ts_models(f):
                    models[model.name] = model
            except Exception as e:
                logger.debug(f"Failed to extract TypeScript models from {f}: {e}")

    return models


def _get_matches(query: Query, root_node) -> list:
    if QueryCursor is not None:
        cursor = QueryCursor(query)
        return cursor.matches(root_node)
    else:
        return query.matches(root_node)


def _extract_python_models(file_path: Path) -> List[ModelDefinition]:
    import tree_sitter_python as tspython

    try:
        lang = Language(tspython.language())
    except TypeError:
        lang = Language(tspython.language(), "python")

    parser = Parser(lang)
    try:
        source = file_path.read_bytes()
    except (IOError, OSError):
        return []

    tree = parser.parse(source)
    # Query for class definitions
    query = Query(lang, "(class_definition name: (identifier) @class_name) @class")
    matches = _get_matches(query, tree.root_node)

    models = []
    for match in matches:
        captures = match[1]
        class_nodes = captures.get("class", [])
        for class_node in class_nodes:
            name_node = class_node.child_by_field_name("name")
            if not name_node:
                continue
            class_name = name_node.text.decode("utf-8")

            # Extract decorators
            decorators = []
            parent = class_node.parent
            if parent and parent.type == "decorated_definition":
                for child in parent.children:
                    if child.type == "decorator":
                        decorators.append(child.text.decode("utf-8").strip().lstrip("@"))

            # Extract base classes
            base_classes = []
            superclasses = class_node.child_by_field_name("superclasses")
            if superclasses:
                for child in superclasses.children:
                    if child.type in ("identifier", "attribute"):
                        base_classes.append(child.text.decode("utf-8"))

            # Extract fields
            fields = []
            body = class_node.child_by_field_name("body")
            if body:
                for stmt in body.children:
                    actual_stmt = stmt
                    if stmt.type == "expression_statement" and len(stmt.children) > 0:
                        actual_stmt = stmt.children[0]

                    if actual_stmt.type in ("assignment", "annotated_assignment"):
                        f_name_node = actual_stmt.child_by_field_name("left") or actual_stmt.child_by_field_name("name")
                        f_type_node = actual_stmt.child_by_field_name("type")
                        f_value_node = actual_stmt.child_by_field_name("right") or actual_stmt.child_by_field_name("value")
                        if f_name_node and f_type_node:
                            f_name = f_name_node.text.decode("utf-8")
                            f_type = f_type_node.text.decode("utf-8")
                            f_default = f_value_node.text.decode("utf-8") if f_value_node else None
                            fields.append(ModelField(name=f_name, type_hint=f_type, default=f_default))

            # Determine if this class is a data model
            is_dataclass = any("dataclass" in dec for dec in decorators)
            is_pydantic_or_typeddict = any(b in ("BaseModel", "TypedDict") for b in base_classes)
            has_fields = len(fields) > 0

            if is_dataclass or is_pydantic_or_typeddict or (has_fields and class_name[0].isupper()):
                models.append(
                    ModelDefinition(
                        name=class_name,
                        file=str(file_path),
                        line=class_node.start_point[0] + 1,
                        base_classes=base_classes,
                        fields=fields,
                    )
                )

    return models


def _extract_go_models(file_path: Path) -> List[ModelDefinition]:
    import tree_sitter_go as tsgo

    try:
        lang = Language(tsgo.language())
    except TypeError:
        lang = Language(tsgo.language(), "go")

    parser = Parser(lang)
    try:
        source = file_path.read_bytes()
    except (IOError, OSError):
        return []

    tree = parser.parse(source)
    query = Query(
        lang,
        """
        (type_spec
          name: (type_identifier) @struct_name
          type: (struct_type) @struct_type)
        """,
    )
    matches = _get_matches(query, tree.root_node)

    models = []
    for match in matches:
        captures = match[1]
        struct_names = captures.get("struct_name", [])
        struct_types = captures.get("struct_type", [])

        if not struct_names or not struct_types:
            continue

        struct_name = struct_names[0].text.decode("utf-8")
        struct_node = struct_types[0]

        fields = []
        field_list = None
        for child in struct_node.children:
            if child.type == "field_declaration_list":
                field_list = child
                break

        if field_list:
            for decl in field_list.children:
                if decl.type == "field_declaration":
                    names = []
                    type_node = decl.child_by_field_name("type")
                    tag_node = decl.child_by_field_name("tag")
                    tag_val = tag_node.text.decode("utf-8").strip("`") if tag_node else None

                    # If names are present as child field_identifiers, collect them
                    for child in decl.children:
                        if child.type == "field_identifier":
                            names.append(child.text.decode("utf-8"))

                    if not names and type_node:
                        # Embedded field: name is type name
                        names.append(type_node.text.decode("utf-8").lstrip("*"))

                    if type_node:
                        f_type = type_node.text.decode("utf-8")
                        for f_name in names:
                            fields.append(ModelField(name=f_name, type_hint=f_type, default=tag_val))

        models.append(
            ModelDefinition(
                name=struct_name,
                file=str(file_path),
                line=struct_names[0].start_point[0] + 1,
                base_classes=[],
                fields=fields,
            )
        )

    return models


def _extract_ts_models(file_path: Path) -> List[ModelDefinition]:
    lang = None
    try:
        import tree_sitter_typescript as ts_typescript
        try:
            lang = Language(ts_typescript.language_typescript())
        except TypeError:
            lang = Language(ts_typescript.language_typescript(), "typescript")
    except ImportError:
        try:
            import tree_sitter_javascript as ts_javascript
            try:
                lang = Language(ts_javascript.language())
            except TypeError:
                lang = Language(ts_javascript.language(), "javascript")
        except ImportError:
            return []

    if not lang:
        return []

    parser = Parser(lang)
    try:
        source = file_path.read_bytes()
    except (IOError, OSError):
        return []

    tree = parser.parse(source)
    query = Query(
        lang,
        """
        [
          (interface_declaration
            (type_identifier) @model_name
            (interface_body) @body)
          (type_alias_declaration
            (type_identifier) @model_name
            (object_type) @body)
        ]
        """,
    )
    matches = _get_matches(query, tree.root_node)

    models = []
    for match in matches:
        captures = match[1]
        model_names = captures.get("model_name", [])
        bodies = captures.get("body", [])

        if not model_names or not bodies:
            continue

        model_name = model_names[0].text.decode("utf-8")
        body_node = bodies[0]

        # Extract bases if interface has extends clause
        base_classes = []
        parent = model_names[0].parent
        if parent and parent.type == "interface_declaration":
            extends_clause = parent.child_by_field_name("extends")
            if not extends_clause:
                # Walk children to look for extends_clause or extends_type_clause
                for child in parent.children:
                    if child.type in ("extends_clause", "extends_type_clause"):
                        extends_clause = child
                        break
            if extends_clause:
                for child in extends_clause.children:
                    if child.type == "type_identifier":
                        base_classes.append(child.text.decode("utf-8"))

        fields = []
        for member in body_node.children:
            if member.type == "property_signature":
                name_node = member.child_by_field_name("name")
                type_node = member.child_by_field_name("type")
                if name_node:
                    f_name = name_node.text.decode("utf-8")
                    f_type = type_node.text.decode("utf-8").lstrip(": ").strip() if type_node else "any"

                    is_optional = False
                    for child in member.children:
                        if child.type == "?":
                            is_optional = True
                            break
                    if is_optional:
                        f_type = f"{f_type} (optional)"

                    fields.append(ModelField(name=f_name, type_hint=f_type, default=None))

        models.append(
            ModelDefinition(
                name=model_name,
                file=str(file_path),
                line=model_names[0].start_point[0] + 1,
                base_classes=base_classes,
                fields=fields,
            )
        )

    return models
