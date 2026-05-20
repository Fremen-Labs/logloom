# Graph Schema Reference

The knowledge graph produced by `logloom build` adheres to a strict JSON schema that maps the static semantic context of your codebase.

## Root Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `schema_version` | String | The version of the LogLoom schema (currently `"1.2"`). |
| `project` | String | The name of the project configured in `.logloomrc.toml`. |
| `built_at` | String (ISO 8601) | The UTC timestamp when the graph was generated. |
| `commit_sha` | String (Optional) | The Git commit hash at the time of the build. |
| `branch` | String (Optional) | The Git branch at the time of the build. |
| `redacted_patterns` | Array of Strings | List of redaction patterns applied during the build. |
| `nodes` | Object | A map where the keys are the `ll:` node IDs and the values are `GraphNode` objects. |
| `coverage` | Object (Optional) | Scan completeness and logging coverage metrics. Adheres to the [CoverageMetrics](#coveragemetrics-object) schema. |
| `models` | Object | A map from model name to [ModelDefinition](#modeldefinition-object) objects. |
| `imports` | Object | A map where the keys are module names and the values are lists of imported modules. |

## GraphNode Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `node_id` | String | The deterministic `ll:` identifier. |
| `file` | String | The relative file path to the log statement. |
| `module` | String | The language-specific module path (e.g., `app.services.auth`). |
| `function` | String | The innermost enclosing function name (or `<module>`). |
| `level` | String | The logging severity level (e.g., `info`, `error`). |
| `message_template` | String | The extracted template string (with variable interpolations replaced by `{}`). |
| `line` | Integer | The 1-indexed line number in the source file. |
| `semantic_tags` | Array of Strings | Inferred tags based on context (e.g., `["error", "auth"]`). |
| `lexical_parents` | Array of Strings | The structural scopes containing the log statement. |
| `call_parents` | Array of Strings | Opaque `ll:` node IDs of direct caller scopes. |
| `call_children` | Array of Strings | Opaque `ll:` node IDs of direct callee scopes. |
| `call_parent_names` | Array of Strings | Human-readable function names of callers (useful for Kibana/Lens visualization). |
| `call_child_names` | Array of Strings | Human-readable function names of callees, including uninstrumented functions. |
| `signature` | Object (Optional) | Detailed function signature of the enclosing function. Adheres to the [FunctionSignature](#functionsignature-object) schema. |

## FunctionSignature Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `parameters` | Array of Objects | List of parameters of the function. Each object adheres to the [Parameter](#parameter-object) schema. |
| `return_type` | String (Optional) | The return type annotation or signature of the function (e.g., `-> bool`, `(bool, error)`, `Promise<void>`). |
| `is_async` | Boolean | Whether the function is declared async/coroutine (`true` for Python `async def`, JS `async function`, etc.). |
| `decorators` | Array of Strings | List of decorator names applied to the function (e.g., `["route('/login')", "auth_required"]`). |

## Parameter Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `name` | String | The parameter name (excluding `self`/`cls` in Python). |
| `type_hint` | String (Optional) | The type annotation or type hint for this parameter. |
| `default` | String (Optional) | The default value for this parameter if defined in the signature. |

## CoverageMetrics Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `total_functions` | Integer | Total number of defined functions/methods found in the scanned files. |
| `instrumented_functions` | Integer | Number of defined functions containing at least one log call. |
| `coverage_pct` | Float | Percentage of functions that are instrumented (range: `0.0` - `100.0`). |
| `uninstrumented` | Array of Strings | Qualified names of defined functions that do not contain any log call sites (format: `module:function`). |

## ModelDefinition Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `name` | String | The name of the data model class, Go struct, or TypeScript interface/type. |
| `file` | String | The file path containing the data model definition. |
| `line` | Integer | The 1-indexed line number where the model is defined. |
| `base_classes` | Array of Strings | List of base classes or extended interfaces (e.g. `["BaseModel"]`, `["BaseTask"]`). |
| `fields` | Array of Objects | List of fields defining the model. Each object adheres to the [ModelField](#modelfield-object) schema. |

## ModelField Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `name` | String | The field/property identifier name. |
| `type_hint` | String (Optional) | The type hint or annotation for the field. |
| `default` | String (Optional) | The default value or Go tag associated with the field. |
