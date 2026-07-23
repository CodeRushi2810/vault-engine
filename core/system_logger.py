import logging
import colorlog
import sys

class SuppressRogueErrors:
    def __init__(self, stream):
        self.stream = stream
    def write(self, text):
        # The rogue library prints "Error: \n" or "Error: <exception>\n"
        if text.strip() == "Error:" or text.startswith("Error: \n"):
            return
        # If there's an empty Error: we swallow it
        self.stream.write(text)
    def flush(self):
        self.stream.flush()
    def __getattr__(self, attr):
        return getattr(self.stream, attr)

# Globally patch stdout/stderr to swallow naked "Error: " traces
sys.stdout = SuppressRogueErrors(sys.stdout)
sys.stderr = SuppressRogueErrors(sys.stderr)

def setup_logger(name="TheVault"):
    logger = logging.getLogger(name)
    
    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    log_colors = {
        'DEBUG':    'cyan',
        'INFO':     'green',
        'WARNING':  'yellow',
        'ERROR':    'red',
        'CRITICAL': 'red,bg_white',
    }

    formatter = colorlog.ColoredFormatter(
        "%(log_color)s[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors=log_colors
    )

    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    import os
    from logging.handlers import RotatingFileHandler
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "vault.log")
    
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=2)
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Suppress growwapi logs to prevent raw 'Error:' spam
    logging.getLogger("growwapi").setLevel(logging.CRITICAL)
    logging.getLogger("growwapi.groww").setLevel(logging.CRITICAL)
    logging.getLogger("growwapi.groww.nats_client").setLevel(logging.CRITICAL)
    for name in logging.root.manager.loggerDict:
        if name.startswith("growwapi"):
            logging.getLogger(name).setLevel(logging.CRITICAL)

    return logger
