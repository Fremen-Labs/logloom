;; go_logs.scm — Tree-sitter query for Go log calls
;;
;; Matches the major Go logging patterns:
;;   - stdlib: log.Printf, log.Println, log.Fatalf
;;   - slog:   slog.Info, slog.Warn, slog.Error, slog.Debug
;;   - zap:    logger.Info, logger.Warn, logger.Error, logger.Debug
;;   - logrus: logrus.Info, log.WithFields(...).Info(...)

;; Pattern 1: attribute calls — log.Printf(...), logger.Info(...)
(call_expression
  function: (selector_expression
    operand: (_)
    field: (field_identifier) @log_method)
  (#match? @log_method "^(Debug|Debugf|Debugw|Debugln|Info|Infof|Infow|Infoln|Warn|Warnf|Warnw|Warnln|Error|Errorf|Errorw|Errorln|Fatal|Fatalf|Fatalw|Fatalln|Panic|Panicf|Panicln|Print|Printf|Println|Log|Logf)$")
  arguments: (argument_list . (_) @first_arg)
) @log_call

;; Pattern 2: package-level calls — fmt.Printf (for completeness)
(call_expression
  function: (selector_expression
    operand: (identifier) @pkg (#match? @pkg "^(log|slog|logrus|zap|zerolog|fmt)$")
    field: (field_identifier) @log_method)
  arguments: (argument_list . (_) @first_arg)
) @log_call_pkg
