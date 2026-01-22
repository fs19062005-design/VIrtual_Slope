import logging, os
from datetime import datetime
from logging import Formatter, StreamHandler, FileHandler
from src.config import config

_initialized = False


def init_logging():

    global _initialized
    if _initialized:
        return

    console_level_name = config.console_log_level
    console_level = getattr(logging, console_level_name.upper(), logging.INFO)
    
    file_level_name = config.file_log_level
    file_level = getattr(logging, file_level_name.upper(), logging.DEBUG)
    
    # Set root logger to most verbose level to capture everything
    root_level = min(console_level, file_level)

    if not os.path.exists(config.log_directory):
        os.makedirs(config.log_directory)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(config.log_directory, f"vs_{timestamp}.log")

    root = logging.getLogger()
    root.setLevel(root_level)

    # Formatter
    fmt = Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s', '%Y-%m-%d %H:%M:%S')

    # Stream handler (console) - uses console_log_level
    sh = StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(console_level)

    # File handler - uses file_log_level
    fh = FileHandler(log_file, encoding='utf-8')
    fh.setFormatter(fmt)
    fh.setLevel(file_level)

    # Attach handlers only if similar handlers are not already present
    # Use presence of handlers as a simple idempotency guard
    if not root.handlers:
        root.addHandler(sh)
        root.addHandler(fh)
    else:
        # Ensure we don't add duplicate handler types
        types = {type(h) for h in root.handlers}
        if StreamHandler not in types:
            root.addHandler(sh)
        if FileHandler not in types:
            root.addHandler(fh)
    
    # Suppress noisy third-party library loggers
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)

    _initialized = True