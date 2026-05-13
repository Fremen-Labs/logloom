;; ts_logs.scm — Tree-sitter query for TypeScript/JavaScript log calls
;;
;; Matches the major TS/JS logging patterns:
;;   - console: console.log, console.warn, console.error, console.debug
;;   - winston: logger.info, logger.warn, logger.error
;;   - pino:   logger.info, logger.warn, logger.error
;;   - bunyan: logger.info, logger.warn, logger.error

;; Pattern 1: attribute calls — console.log(...), logger.info(...)
(call_expression
  function: (member_expression
    property: (property_identifier) @log_method)
  (#match? @log_method "^(log|info|warn|error|debug|trace|fatal|verbose|silly)$")
  arguments: (arguments . (_) @first_arg)
) @log_call

;; Pattern 2: console-specific — console.log(...)
(call_expression
  function: (member_expression
    object: (identifier) @obj (#eq? @obj "console")
    property: (property_identifier) @log_method)
  arguments: (arguments . (_) @first_arg)
) @log_call_console
