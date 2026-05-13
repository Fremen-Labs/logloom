/**
 * sample_app.ts — Realistic TypeScript application for LogLoom scanner testing.
 * Exercises: console.*, winston, pino, NestJS Logger, class methods,
 * arrow functions, async/await, template literals, try/catch, loops.
 */

import winston from "winston";
import pino from "pino";

const logger = winston.createLogger({ level: "info", transports: [] });
const pinoLogger = pino();

// ── Top-level logging ────────────────────────────────────────────────────────

console.log("Application bootstrapping");

// ── Named function ───────────────────────────────────────────────────────────

function handleLogin(username: string, password: string): boolean {
    console.log("Login attempt received");
    logger.info("Authenticating user");

    if (!username) {
        console.error("Missing username in login request");
        logger.warn("Empty username submitted to login endpoint");
        return false;
    }

    try {
        console.debug("Calling authentication service");
        logger.debug("Auth service call initiated");
    } catch (e) {
        logger.error("Auth service unreachable");
        console.error("Fatal authentication error occurred");
    }

    return true;
}

// ── Arrow function ───────────────────────────────────────────────────────────

const processPayment = (orderId: string, amount: number): void => {
    logger.info("Processing payment for order");
    console.log(`Order ${orderId} payment processing started`);
    pinoLogger.warn("Payment gateway latency detected");

    if (amount > 10000) {
        logger.warn("High-value transaction flagged for review");
    }

    console.debug(`Charging ${amount} for order ${orderId}`);
};

// ── Class with methods ───────────────────────────────────────────────────────

class UserService {
    private readonly logger = winston.createLogger({ level: "info" });

    async createUser(email: string): Promise<void> {
        console.log("Creating user account");
        this.logger.info("User registration workflow started");

        try {
            console.debug(`Sending welcome email to ${email}`);
            this.logger.debug("Welcome email queued");
        } catch (err) {
            this.logger.error("User creation pipeline failed");
            console.error("Registration error — rolling back");
        }
    }

    deleteUser(id: string): void {
        this.logger.warn("User deletion initiated — soft delete");
        console.log("Marking user as deleted in database");
    }
}

// ── Express-style middleware (arrow) ─────────────────────────────────────────

const authMiddleware = (req: any, res: any, next: Function): void => {
    console.log("Auth middleware executing on incoming request");
    logger.debug("Checking authorization header");

    if (!req.headers?.authorization) {
        logger.warn("Missing authorization header");
        console.error("Unauthorized request — rejecting");
        return;
    }

    next();
};

// ── Async function ───────────────────────────────────────────────────────────

async function fetchData(url: string): Promise<any> {
    console.log("Fetching remote data");
    try {
        logger.info("HTTP request initiated");
        logger.debug(`GET request to ${url}`);
        return {};
    } catch (error) {
        console.error("Remote fetch failed");
        logger.error("Remote data unavailable — circuit breaker open");
        return null;
    }
}

// ── Retry loop ───────────────────────────────────────────────────────────────

async function retryOperation(maxRetries: number): Promise<void> {
    for (let i = 0; i < maxRetries; i++) {
        console.log(`Retry attempt ${i + 1}/${maxRetries}`);
        try {
            logger.info("Operation attempt executing");
            return;
        } catch (e) {
            logger.warn("Operation failed — scheduling retry");
            if (i === maxRetries - 1) {
                pinoLogger.error("All retries exhausted");
            }
        }
    }
}

// ── Export ────────────────────────────────────────────────────────────────────

export default function shutdown(): void {
    console.warn("Application shutting down gracefully");
    logger.info("Graceful shutdown initiated — draining connections");
    pinoLogger.fatal("Critical shutdown event — process exiting");
}
