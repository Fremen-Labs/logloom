"""Sample application for demonstrating LogLoom intelligence features."""

import logging

logger = logging.getLogger(__name__)


def validate_input(data):
    """Validates incoming request data."""
    logger.debug("Validating input data")
    if not data:
        logger.error("Empty input received")
        return False
    return True


def authenticate_user(username, password):
    """Authenticates a user against the database."""
    try:
        logger.info(f"Authenticating user {username}")
        if not validate_input(username):
            logger.warning("Invalid username provided")
            return None
        logger.info("Authentication successful")
        return {"user": username, "token": "abc123"}
    except Exception as e:
        logger.exception(f"Authentication failed for {username}")
        return None


def process_payment(order_id, amount):
    """Processes a payment charge."""
    logger.info(f"Processing payment for order {order_id}")
    if not validate_input(order_id):
        logger.error("Invalid order ID")
        return False

    try:
        logger.info(f"Charging {amount} for order {order_id}")
        charge_stripe(order_id, amount)
        logger.info("Payment processed successfully")
        return True
    except Exception:
        logger.exception("Payment charge failed — retrying")
        return False


def charge_stripe(order_id, amount):
    """Calls the Stripe API."""
    logger.debug(f"Stripe API call for order {order_id}")


def startup():
    """Application startup routine."""
    logger.info("Application starting up")
    logger.info("Loading configuration")


def shutdown():
    """Application shutdown routine."""
    logger.info("Application shutting down")
    logger.warning("Flushing remaining queues")
