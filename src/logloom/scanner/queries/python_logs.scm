;; python_logs.scm - Comprehensive Tree-sitter query for log calls

;; Pattern 1: attribute calls (logger.info, self.logger.error, self.log)
(call
  function: (attribute
    attribute: (identifier) @log_method)
  (#match? @log_method "^(debug|info|warning|error|critical|exception|fatal|log)$")
  arguments: (argument_list . (_) @first_arg)
) @log_call

;; Pattern 2: module-level calls (logging.info)
(call
  function: (attribute
    object: (identifier) @mod (#eq? @mod "logging")
    attribute: (identifier) @log_method)
  arguments: (argument_list . (_) @first_arg)
) @log_call_module

;; Pattern 3: direct calls (if log/info/etc are imported directly)
(call
  function: (identifier) @log_method
  (#match? @log_method "^(debug|info|warning|error|critical|exception|fatal|log)$")
  arguments: (argument_list . (_) @first_arg)
) @log_call_direct