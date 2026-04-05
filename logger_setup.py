import logging
import os

def setup_logger(log_file: str = "bot.log") -> logging.Logger:
    logger = logging.getLogger("rain_bot")
    logger.setLevel(logging.DEBUG)

    # Console handler — INFO level
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    ))

    # File handler — DEBUG level
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), log_file)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
