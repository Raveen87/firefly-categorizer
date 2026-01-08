import logging
import logging.config
import sys
import os

class ColourizedFormatter(logging.Formatter):
    """
    Custom formatter to add colors to log levels.
    """
    # ANSI escape codes
    GREY = "\x1b[38;20m"
    GREEN = "\x1b[32;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"
    
    LEVEL_COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record):
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

def get_logging_config():
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "firefly_categorizer.logger.ColourizedFormatter",
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
            },
        },
        "loggers": {
            "": {  # Root logger
                "handlers": ["console"],
                "level": log_level_name,
            },
            "uvicorn": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False
            },
            "uvicorn.error": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False
            }, 
            "uvicorn.access": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False
            },
        },
    }

def setup_logging():
    logging.config.dictConfig(get_logging_config())

def get_logger(name: str):
    return logging.getLogger(name)
