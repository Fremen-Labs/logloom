;; go_logs.scm — Tree-sitter query for Go log calls
;;
;; Matches the major Go logging patterns:
;;   - stdlib:   log.Printf, log.Println, log.Fatalf
;;   - slog:     slog.Info, slog.Warn, slog.Error, slog.Debug
;;   - zap:      logger.Info, logger.Warn, sugar.Infof
;;   - logrus:   logrus.Info, log.WithFields(...).Info(...)
;;   - zerolog:  log.Info().Msg("..."), log.Error().Err(err).Msg("...")

;; ─── Pattern 1: Direct method calls ─────────────────────────────────────────
;; Matches: log.Printf(...), slog.Info(...), logger.Info(...), sugar.Warnf(...)
;; This is the primary pattern for stdlib, slog, zap, and logrus.
(call_expression
  function: (selector_expression
    operand: (_)
    field: (field_identifier) @log_method)
  (#match? @log_method "^(Debug|Debugf|Debugw|Debugln|Info|Infof|Infow|Infoln|Warn|Warnf|Warnw|Warnln|Error|Errorf|Errorw|Errorln|Fatal|Fatalf|Fatalw|Fatalln|Panic|Panicf|Panicln|Print|Printf|Println|Log|Logf|DPanic|DPanicf|DPanicw)$")
  arguments: (argument_list . (_) @first_arg)
) @log_call

;; ─── Pattern 2: Zerolog chain — .Msg("text") / .Msgf("text %s", v) ──────────
;; Zerolog uses builder chains: log.Info().Str("k","v").Msg("message")
;; The terminal .Msg() / .Msgf() is the log emission point.
(call_expression
  function: (selector_expression
    operand: (call_expression)
    field: (field_identifier) @log_method)
  (#match? @log_method "^(Msg|Msgf|Send)$")
  arguments: (argument_list . (_) @first_arg)
) @log_call_zerolog

;; ─── Pattern 3: Zerolog .Msg() with no arguments (.Send()) ──────────────────
;; log.Info().Send()  — no message, just emit
(call_expression
  function: (selector_expression
    operand: (call_expression)
    field: (field_identifier) @log_method)
  (#match? @log_method "^(Send)$")
  arguments: (argument_list)
) @log_call_zerolog_send
