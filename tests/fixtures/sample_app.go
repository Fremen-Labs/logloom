package main

// sample_app.go — Realistic Go application for LogLoom scanner testing.
// Exercises: stdlib log, slog, zap (typed + sugar), logrus, zerolog,
// method receivers, nested control flow, deferred functions, goroutines.

import (
	"fmt"
	"log"
	"log/slog"
	"net/http"

	"github.com/rs/zerolog"
	zlog "github.com/rs/zerolog/log"
	"github.com/sirupsen/logrus"
	"go.uber.org/zap"
)

// ── stdlib log ───────────────────────────────────────────────────────────────

func startServer(port int) {
	log.Printf("Starting server on port %d", port)
	log.Println("Listening for connections")
}

func shutdownServer() {
	log.Fatalf("Forced shutdown: %v", fmt.Errorf("timeout"))
}

// ── slog (Go 1.21+) ─────────────────────────────────────────────────────────

func handleRequest(w http.ResponseWriter, r *http.Request) {
	slog.Info("request received", "method", r.Method, "path", r.URL.Path)
	slog.Debug("parsing request body", "content_type", r.Header.Get("Content-Type"))
	if r.Method == "DELETE" {
		slog.Warn("destructive operation", "endpoint", r.URL.Path)
	}
	if err := processRequest(r); err != nil {
		slog.Error("request processing failed", "err", err, "status", 500)
	}
}

func processRequest(r *http.Request) error {
	slog.Info("processing request payload")
	return nil
}

// ── zap ──────────────────────────────────────────────────────────────────────

func zapTypedExample(logger *zap.Logger) {
	logger.Info("User authenticated", zap.String("user_id", "u-123"))
	logger.Warn("Rate limit approaching", zap.Int("remaining", 5))
	logger.Error("Database connection lost", zap.Error(fmt.Errorf("timeout")))
	logger.Debug("Cache hit ratio", zap.Float64("ratio", 0.95))
}

func zapSugarExample(logger *zap.Logger) {
	sugar := logger.Sugar()
	sugar.Infof("Processing %d items in batch", 42)
	sugar.Warnf("Slow query took %v", "2.5s")
	sugar.Errorf("Failed to process item %s: %v", "item-1", fmt.Errorf("bad"))
}

// ── logrus ───────────────────────────────────────────────────────────────────

func logrusExamples() {
	logrus.Info("Application starting")
	logrus.Warnf("Config file missing, using defaults: %s", "/etc/app.conf")
	logrus.Errorf("Fatal DB error: %v", fmt.Errorf("connection refused"))
	logrus.WithFields(logrus.Fields{
		"user":  "admin",
		"event": "login",
	}).Info("User logged in")
}

// ── zerolog (chained builder) ────────────────────────────────────────────────

func zerologExamples(logger zerolog.Logger) {
	zlog.Info().Msg("Server started successfully")
	zlog.Error().Err(fmt.Errorf("db timeout")).Msg("Request processing failed")
	zlog.Debug().Str("cache_key", "user:123").Msg("Cache lookup")
	zlog.Warn().Int("retry_count", 3).Msg("Retrying operation")
	zlog.Fatal().Msg("Unrecoverable error — shutting down")
}

// ── Method receiver ──────────────────────────────────────────────────────────

type AuthService struct {
	logger *zap.Logger
}

func (a *AuthService) Authenticate(token string) error {
	a.logger.Info("Authentication attempt", zap.String("token_prefix", token[:8]))
	if token == "" {
		a.logger.Error("Empty token provided")
		return fmt.Errorf("empty token")
	}
	a.logger.Info("Authentication successful")
	return nil
}

// ── Error handling with defer ────────────────────────────────────────────────

func riskyOperation() {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("Recovered from panic: %v", r)
		}
	}()
	slog.Info("Starting risky operation")
}

// ── Complex control flow ─────────────────────────────────────────────────────

func retryWithBackoff(userID string) {
	for i := 0; i < 3; i++ {
		slog.Info("Attempting token refresh", "attempt", i+1, "user", userID)
		if err := refreshToken(userID); err != nil {
			slog.Error("Token refresh failed", "attempt", i+1, "err", err)
		} else {
			slog.Info("Token refreshed successfully", "user", userID)
			return
		}
	}
	slog.Error("All retry attempts exhausted", "user", userID)
}

func refreshToken(userID string) error { return nil }

func main() {
	log.Println("LogLoom Go sample application")
}
