import datetime
import json
import os
import sqlite3
from typing import Optional, List, Dict, Any

DEFAULT_DB_PATH = os.path.join("data", "scheduler.db")


class SchedulerDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS job_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_sec REAL,
                    keywords_total INTEGER DEFAULT 0,
                    keywords_success INTEGER DEFAULT 0,
                    keywords_failed INTEGER DEFAULT 0,
                    places_count INTEGER DEFAULT 0,
                    error_summary TEXT,
                    output_files TEXT,
                    log_file TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS job_states (
                    job_name TEXT PRIMARY KEY,
                    last_status TEXT,
                    last_run_id INTEGER,
                    last_started_at TEXT,
                    last_finished_at TEXT,
                    next_run_at TEXT,
                    total_runs INTEGER DEFAULT 0,
                    total_failures INTEGER DEFAULT 0,
                    last_error TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_job_runs_job_name ON job_runs(job_name);
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_job_runs_status ON job_runs(status);
                """
            )
            conn.commit()

    def mark_stale_running_as_interrupted(self):
        """Đánh dấu các tác vụ đang RUNNING thành INTERRUPTED nếu daemon bị tắt bất ngờ."""
        now = datetime.datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE job_runs
                SET status = 'INTERRUPTED',
                    finished_at = ?,
                    error_summary = 'Tiến trình bị ngắt đột ngột (daemon restart/stop)'
                WHERE status = 'RUNNING'
                """,
                (now,),
            )
            cursor.execute(
                """
                UPDATE job_states
                SET last_status = 'INTERRUPTED',
                    last_finished_at = ?
                WHERE last_status = 'RUNNING'
                """,
                (now,),
            )
            conn.commit()

    def start_run(self, job_name: str, total_keywords: int, log_file: str) -> int:
        now = datetime.datetime.now().isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO job_runs (
                    job_name, status, started_at, keywords_total, log_file
                ) VALUES (?, 'RUNNING', ?, ?, ?)
                """,
                (job_name, now, total_keywords, log_file),
            )
            run_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO job_states (
                    job_name, last_status, last_run_id, last_started_at, total_runs
                ) VALUES (?, 'RUNNING', ?, ?, 1)
                ON CONFLICT(job_name) DO UPDATE SET
                    last_status = 'RUNNING',
                    last_run_id = excluded.last_run_id,
                    last_started_at = excluded.last_started_at,
                    total_runs = total_runs + 1
                """,
                (job_name, run_id, now),
            )
            conn.commit()
            return run_id

    def finish_run(
        self,
        run_id: int,
        status: str,
        keywords_success: int,
        keywords_failed: int,
        places_count: int,
        error_summary: Optional[str] = None,
        output_files: Optional[List[str]] = None,
    ):
        now_dt = datetime.datetime.now()
        now = now_dt.isoformat()
        out_json = json.dumps(output_files or [], ensure_ascii=False)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT job_name, started_at FROM job_runs WHERE id = ?", (run_id,)
            )
            row = cursor.fetchone()
            if not row:
                return

            job_name = row["job_name"]
            started_dt = datetime.datetime.fromisoformat(row["started_at"])
            duration_sec = round((now_dt - started_dt).total_seconds(), 2)

            cursor.execute(
                """
                UPDATE job_runs
                SET status = ?,
                    finished_at = ?,
                    duration_sec = ?,
                    keywords_success = ?,
                    keywords_failed = ?,
                    places_count = ?,
                    error_summary = ?,
                    output_files = ?
                WHERE id = ?
                """,
                (
                    status,
                    now,
                    duration_sec,
                    keywords_success,
                    keywords_failed,
                    places_count,
                    error_summary,
                    out_json,
                    run_id,
                ),
            )

            is_fail = 1 if status in ("FAILED", "PARTIAL") else 0
            cursor.execute(
                """
                UPDATE job_states
                SET last_status = ?,
                    last_finished_at = ?,
                    total_failures = total_failures + ?,
                    last_error = ?
                WHERE job_name = ?
                """,
                (status, now, is_fail, error_summary, job_name),
            )
            conn.commit()

    def update_next_run(self, job_name: str, next_run_at: Optional[str]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO job_states (job_name, next_run_at)
                VALUES (?, ?)
                ON CONFLICT(job_name) DO UPDATE SET
                    next_run_at = excluded.next_run_at
                """,
                (job_name, next_run_at),
            )
            conn.commit()

    def get_job_state(self, job_name: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM job_states WHERE job_name = ?", (job_name,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_job_states(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM job_states ORDER BY job_name ASC")
            return [dict(r) for r in cursor.fetchall()]

    def get_recent_runs(
        self, job_name: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if job_name:
                cursor.execute(
                    """
                    SELECT * FROM job_runs
                    WHERE job_name = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (job_name, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM job_runs ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            return [dict(r) for r in cursor.fetchall()]

    def get_failed_runs(self, limit: int = 15) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM job_runs
                WHERE status IN ('FAILED', 'PARTIAL', 'INTERRUPTED')
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM job_runs WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
