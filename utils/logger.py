"""Centralized logging for Highbourne Terminal."""
import logging
import sys
from pathlib import Path

def setup_logging(level=logging.INFO):
    """Configure logging with console + file output."""
    logger = logging.getLogger("highbourne")
    logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )

    # Console
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File (if writable)
    try:
        log_path = Path(__file__).parent.parent / "highbourne.log"
        file_handler = logging.FileHandler(log_path, mode='a')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        pass

    return logger

log = setup_logging()
