import sqlite3
import os
import time
from typing import Any, Optional, Dict
from pydantic import BaseModel
from loguru import logger

from controlplane.config import UserContext, PolicyProfile, UserRole

DB_PATH = os.path.join("data", "governance.db")

_DEFAULT_POLICIES = {
    "customer_support": PolicyProfile(
        name="customer_support",
        align_score_threshold=0.60,
        guard_block_composite_threshold=0.60,
        guard_block_signal_threshold=0.85,
        pii_masking_enabled=True,
        quarantine_on_warn=True,
        latency_priority="low",
        assurance_level="medium"
    ),
    "internal_copilot": PolicyProfile(
        name="internal_copilot",
        align_score_threshold=0.70,
        guard_block_composite_threshold=0.50,
        guard_block_signal_threshold=0.80,
        pii_masking_enabled=False,
        quarantine_on_warn=True,
        latency_priority="medium",
        assurance_level="medium"
    ),
    "regulated_decision": PolicyProfile(
        name="regulated_decision",
        align_score_threshold=0.85,
        guard_block_composite_threshold=0.30,
        guard_block_signal_threshold=0.60,
        pii_masking_enabled=True,
        quarantine_on_warn=True,
        latency_priority="flexible",
        assurance_level="high"
    ),
}

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
                review_action TEXT,
                policy_used TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS policies (
                name TEXT PRIMARY KEY,
                align_score_threshold REAL,
                guard_block_composite_threshold REAL,
                guard_block_signal_threshold REAL,
                pii_masking_enabled INTEGER,
                quarantine_on_warn INTEGER,
                latency_priority TEXT DEFAULT 'medium',
                assurance_level TEXT DEFAULT 'medium'
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS session_risk (
                session_id TEXT PRIMARY KEY,
                cumulative_risk REAL,
                query_count INTEGER,
                last_updated REAL
            )
        ''')

        # Run schema migrations first for existing databases
        try:
            cursor.execute("ALTER TABLE hitl_queue ADD COLUMN policy_used TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE policies ADD COLUMN latency_priority TEXT DEFAULT 'medium'")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE policies ADD COLUMN assurance_level TEXT DEFAULT 'medium'")
        except sqlite3.OperationalError:
            pass

        # Insert defaults if empty
        cursor.execute("SELECT count(*) FROM policies")
        if cursor.fetchone()[0] == 0:
            for p in _DEFAULT_POLICIES.values():
                cursor.execute(
                    "INSERT INTO policies (name, align_score_threshold, guard_block_composite_threshold, guard_block_signal_threshold, pii_masking_enabled, quarantine_on_warn, latency_priority, assurance_level) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (p.name, p.align_score_threshold, p.guard_block_composite_threshold, p.guard_block_signal_threshold, int(p.pii_masking_enabled), int(p.quarantine_on_warn), p.latency_priority, p.assurance_level)
                )

        conn.commit()

init_db()

class PolicyEngine:
    @staticmethod
    def get_policy(context: UserContext) -> PolicyProfile:
        if context.role == UserRole.ADMIN:
            policy_name = "regulated_decision"
        elif context.role == UserRole.INTERNAL:
            policy_name = "internal_copilot"
        else:
            policy_name = "customer_support"

        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM policies WHERE name = ?", (policy_name,)).fetchone()
                if row:
                    return PolicyProfile(
                        name=row["name"],
                        align_score_threshold=row["align_score_threshold"],
                        guard_block_composite_threshold=row["guard_block_composite_threshold"],
                        guard_block_signal_threshold=row["guard_block_signal_threshold"],
                        pii_masking_enabled=bool(row["pii_masking_enabled"]),
                        quarantine_on_warn=bool(row["quarantine_on_warn"]),
                        latency_priority=row["latency_priority"] if "latency_priority" in row.keys() else "balanced",
                        assurance_level=row["assurance_level"] if "assurance_level" in row.keys() else "medium"
                    )
        except Exception as e:
            logger.error(f"Failed to fetch policy from DB: {e}")
        return _DEFAULT_POLICIES[policy_name]

    @staticmethod
    def update_policy(profile: PolicyProfile):
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                conn.execute(
                    "UPDATE policies SET align_score_threshold=?, guard_block_composite_threshold=?, guard_block_signal_threshold=?, pii_masking_enabled=?, quarantine_on_warn=?, latency_priority=?, assurance_level=? WHERE name=?",
                    (profile.align_score_threshold, profile.guard_block_composite_threshold, profile.guard_block_signal_threshold, int(profile.pii_masking_enabled), int(profile.quarantine_on_warn), profile.latency_priority, profile.assurance_level, profile.name)
                )
        except Exception as e:
            logger.error(f"Failed to update policy: {e}")


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
    def enqueue_hitl(query_id: str, original_query: str, raw_output: str, severity: str, policy_used: str = "strict_external"):
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                conn.execute(
                    "INSERT INTO hitl_queue (query_id, original_query, raw_output, severity, status, created_at, policy_used) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (query_id, original_query, raw_output, severity, "PENDING", time.time(), policy_used)
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
        policy_used = "strict_external"
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                # get policy used
                row = conn.execute("SELECT policy_used FROM hitl_queue WHERE query_id = ?", (query_id,)).fetchone()
                if row and row[0]:
                    policy_used = row[0]

                cursor = conn.execute(
                    "UPDATE hitl_queue SET status = ?, review_action = ?, reviewed_by = ? WHERE query_id = ?",
                    ("RESOLVED", action, reviewed_by, query_id)
                )
                if cursor.rowcount > 0:
                    resolved = True
            
            if resolved:
                Governance.log_audit(query_id, reviewed_by, f"HITL_RESOLVED_{action.upper()}", f"Reviewer action: {action}")
                # Feedback loop: check if we should relax threshold for this policy
                Governance._evaluate_feedback_loop(policy_used)
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to resolve HITL item: {e}")
            return False

    @staticmethod
    def _evaluate_feedback_loop(policy_name: str):
        """Active Feedback Loop: dynamically adjust thresholds if false-positive rate is high."""
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                # Get last 20 resolved items for this policy
                cursor = conn.execute(
                    "SELECT review_action FROM hitl_queue WHERE status = 'RESOLVED' AND policy_used = ? ORDER BY created_at DESC LIMIT 20",
                    (policy_name,)
                )
                actions = [row[0] for row in cursor.fetchall()]
                if len(actions) >= 10:
                    approves = actions.count("approve")
                    if approves / len(actions) > 0.8:
                        # 80%+ were approved (false positives). Relax the threshold slightly.
                        logger.info(f"Feedback loop: high false positive rate detected for {policy_name}. Relaxing thresholds.")
                        conn.execute("UPDATE policies SET guard_block_composite_threshold = guard_block_composite_threshold + 0.02 WHERE name = ?", (policy_name,))
        except Exception as e:
            logger.error(f"Feedback loop failed: {e}")

    @staticmethod
    def update_session_risk(session_id: str, risk_score: float) -> float:
        """Track compounding multi-turn risk. Returns new cumulative risk."""
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                row = conn.execute("SELECT cumulative_risk, query_count FROM session_risk WHERE session_id = ?", (session_id,)).fetchone()
                if row:
                    new_risk = row[0] + risk_score
                    new_count = row[1] + 1
                    conn.execute("UPDATE session_risk SET cumulative_risk=?, query_count=?, last_updated=? WHERE session_id=?", 
                                 (new_risk, new_count, time.time(), session_id))
                else:
                    new_risk = risk_score
                    conn.execute("INSERT INTO session_risk (session_id, cumulative_risk, query_count, last_updated) VALUES (?, ?, ?, ?)",
                                 (session_id, risk_score, 1, time.time()))
                return new_risk
        except Exception as e:
            logger.error(f"Session tracking failed: {e}")
            return risk_score
