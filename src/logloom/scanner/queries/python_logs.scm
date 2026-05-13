;; python_logs.scm - Comprehensive Tree-sitter query for log calls
(call
  function: (attribute
    attribute: (identifier) @log_method)
  (#match? @log_method "^(debug|info|warning|error|critical|exception|fatal|log)$")
  arguments: (argument_list . (_) @first_arg)
) @log_call

(call
  function: (attribute
    object: (identifier) @mod (#eq? @mod "logging")
    attribute: (identifier) @log_method)
  arguments: (argument_list . (_) @first_arg)
) @log_call_module