import sqlite3
import os
import time
from typing import Any, Optional, Dict
from pydantic import BaseModel
from loguru import logger

from controlplane.config import UserContext, PolicyProfile, UserRole

# Define default policy profiles
_POLICIES = {
    "strict_external": PolicyProfile(
        name="strict_external",
        align_score_threshold=0.75,
        guard_block_composite_threshold=0.40,
        guard_block_signal_threshold=0.70,
        pii_masking_enabled=True,
        quarantine_on_warn=True,
    ),
    "relaxed_internal": PolicyProfile(
        name="relaxed_internal",
        align_score_threshold=0.50,
        guard_block_composite_threshold=0.60,
        guard_block_signal_threshold=0.85,
        pii_masking_enabled=False,
        quarantine_on_warn=False,
    ),
}

class PolicyEngine:
    @staticmethod
    def get_policy(context: UserContext) -> PolicyProfile:
        """Dynamically resolve policy based on user context."""
        if context.role == UserRole.INTERNAL or context.role == UserRole.ADMIN:
            return _POLICIES["relaxed_internal"]
        return _POLICIES["strict_external"]


# ─────────────────────────────────────────────────────────────
# Database Init & Models
# ─────────────────────────────────────────────────────────────
DB_PATH = os.path.join("data", "governance.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id TEXT,
                user_id TEXT,
                action TEXT,
                timestamp REAL,
                details TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS hitl_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id TEXT,
                original_query TEXT,
                raw_output TEXT,
                severity TEXT,
                status TEXT,
                created_at REAL,
                reviewed_by TEXT,
                review_action TEXT
            )
        ''')
        conn.commit()

init_db()

# ─────────────────────────────────────────────────────────────
# Governance Operations
# ─────────────────────────────────────────────────────────────
class Governance:
    @staticmethod
    def log_audit(query_id: str, user_id: str, action: str, details: str = ""):
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                conn.execute(
                    "INSERT INTO audit_logs (query_id, user_id, action, timestamp, details) VALUES (?, ?, ?, ?, ?)",
                    (query_id, user_id, action, time.time(), details)
                )
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    @staticmethod
    def enqueue_hitl(query_id: str, original_query: str, raw_output: str, severity: str):
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                conn.execute(
                    "INSERT INTO hitl_queue (query_id, original_query, raw_output, severity, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (query_id, original_query, raw_output, severity, "PENDING", time.time())
                )
            logger.info(f"Query {query_id} added to HITL quarantine queue.")
        except Exception as e:
            logger.error(f"Failed to enqueue HITL: {e}")

    @staticmethod
    def get_pending_hitl() -> list[dict]:
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT id, query_id, original_query, raw_output, severity, created_at FROM hitl_queue WHERE status = 'PENDING' ORDER BY created_at DESC"
                )
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to fetch HITL queue: {e}")
            return []

    @staticmethod
    def resolve_hitl(query_id: str, action: str, reviewed_by: str = "admin") -> bool:
        resolved = False
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                cursor = conn.execute(
                    "UPDATE hitl_queue SET status = ?, review_action = ?, reviewed_by = ? WHERE query_id = ?",
                    ("RESOLVED", action, reviewed_by, query_id)
                )
                if cursor.rowcount > 0:
                    resolved = True
            
            if resolved:
                Governance.log_audit(query_id, reviewed_by, f"HITL_RESOLVED_{action.upper()}", f"Reviewer action: {action}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to resolve HITL item: {e}")
            return False
