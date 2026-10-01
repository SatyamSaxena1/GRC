import threading
import time

from sqlalchemy import create_engine, text

from app.db import tune_sqlite


def _engine(tmp_path):
    return tune_sqlite(create_engine(f"sqlite:///{tmp_path / 't.db'}"))


def test_sqlite_gets_wal_and_a_long_busy_timeout(tmp_path):
    with _engine(tmp_path).connect() as c:
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert c.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000


def test_a_second_writer_waits_for_the_first_instead_of_failing(tmp_path):
    """The pipeline crashed with "database is locked" when another writer held the
    lock past SQLite's default 5 s; with the tuned timeout it just waits."""
    eng = _engine(tmp_path)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE t (x INTEGER)"))

    def hold_the_write_lock():
        with eng.begin() as c:
            c.execute(text("INSERT INTO t VALUES (1)"))
            time.sleep(6)

    holder = threading.Thread(target=hold_the_write_lock)
    holder.start()
    time.sleep(0.3)  # let the holder take the lock first
    with eng.begin() as c:  # blocks until the holder commits, then succeeds
        c.execute(text("INSERT INTO t VALUES (2)"))
    holder.join()
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM t")).scalar() == 2


def test_postgres_engine_is_left_alone():
    class Fake:
        class dialect:  # noqa: N801
            name = "postgresql"

    fake = Fake()
    assert tune_sqlite(fake) is fake
