import logging
import logging.config
import os


class ColourizedFormatter(logging.Formatter):
    """
    Custom formatter to add colors to log levels.
    """
    # ANSI escape codes
    GREY = "\x1b[90m"        # Bright black (grey)
    GREEN = "\x1b[32m"       # Green
    YELLOW = "\x1b[33m"      # Yellow
    RED = "\x1b[31m"         # Red
    BOLD_RED = "\x1b[31;1m"  # Bold red
    RESET = "\x1b[0m"        # Reset

    LEVEL_COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        # Save original levelname
        orig_levelname = record.levelname

        # Colorize levelname
        if record.levelno in self.LEVEL_COLORS:
            record.levelname = f"{self.LEVEL_COLORS[record.levelno]}{record.levelname}{self.RESET}"

        # Format
        result = super().format(record)

        # Restore original levelname (to avoid side effects)
        record.levelname = orig_levelname
        return result

def get_logging_config() -> dict:
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_dir = os.getenv("LOG_DIR")
    handlers = {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "default",
        },
    }
    root_handlers = ["console"]
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        handlers["file"] = {
            "class": "logging.FileHandler",
            "filename": os.path.join(log_dir, "app.log"),
            "formatter": "default",
        }
        root_handlers.append("file")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "firefly_categorizer.logger.ColourizedFormatter",
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": handlers,
        "loggers": {
            "": {  # Root logger
                "handlers": root_handlers,
                "level": log_level_name,
            },
            "uvicorn": {
                "handlers": root_handlers,
                "level": "INFO",
                "propagate": False
            },
            "uvicorn.error": {
                "handlers": root_handlers,
                "level": "INFO",
                "propagate": False
            },
            "uvicorn.access": {
                "handlers": root_handlers,
                "level": "INFO",
                "propagate": False
            },
        },
    }

def setup_logging() -> None:
    logging.config.dictConfig(get_logging_config())

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
