;; ts_logs.scm — Tree-sitter query for TypeScript/JavaScript log calls
;;
;; Matches the major TS/JS logging patterns:
;;   - console: console.log, console.warn, console.error, console.debug, console.trace
;;   - winston: logger.info, logger.warn, logger.error, logger.debug
;;   - pino:    logger.info, logger.warn, logger.error, logger.debug, logger.fatal
;;   - bunyan:  logger.info, logger.warn, logger.error, logger.debug, logger.fatal, logger.trace
;;   - NestJS:  this.logger.log, this.logger.warn, this.logger.error
;;   - log4js:  logger.info, logger.warn, logger.error, logger.debug, logger.trace, logger.fatal

;; ─── Pattern 1: Direct member calls ─────────────────────────────────────────
;; Matches: console.log(...), logger.info(...), this.logger.error(...)
;; The widest pattern — catches any obj.method() where method is a known log name.
(call_expression
  function: (member_expression
    property: (property_identifier) @log_method)
  (#match? @log_method "^(log|info|warn|error|debug|trace|fatal|verbose|silly)$")
  arguments: (arguments . (_) @first_arg)
) @log_call

;; ─── Pattern 2: Console-specific (explicit object constraint) ────────────────
;; Matches: console.log(...), console.warn(...)
;; More precise than Pattern 1 for console-only detection.
(call_expression
  function: (member_expression
    object: (identifier) @obj (#eq? @obj "console")
    property: (property_identifier) @log_method)
  arguments: (arguments . (_) @first_arg)
) @log_call_console

;; ─── Pattern 3: Chained logger calls ────────────────────────────────────────
;; Matches: winston.createLogger().info(...), logger.child({}).warn(...)
;; For loggers that return a new logger from .child() / .createLogger()
(call_expression
  function: (member_expression
    object: (call_expression)
    property: (property_identifier) @log_method)
  (#match? @log_method "^(log|info|warn|error|debug|trace|fatal|verbose|silly)$")
  arguments: (arguments . (_) @first_arg)
) @log_call_chained
