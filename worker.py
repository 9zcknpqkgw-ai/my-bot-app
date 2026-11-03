"""Запуск: python worker.py. Нужны те же зависимости и общая bots.sqlite3."""
import logging
import time
from app import init_db, monitor_once

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
init_db()
logging.info("Monitor started. Only confirmed active bots are checked.")
while True:
    try:
        monitor_once()
    except KeyboardInterrupt:
        break
    except Exception:
        # Не выводим URL с токеном и содержимое секретов.
        logging.error("Monitor cycle failed; check server and database.")
    time.sleep(60)
