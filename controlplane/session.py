import json
import sqlite3
import time
from typing import List, Dict, Optional
import redis
from loguru import logger
from controlplane.core.governance import DB_PATH

class SessionManager:
    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379):
        self.redis = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.ttl = 3600 * 2  # 2 hours

    def get_messages(self, session_id: str) -> List[Dict]:
        try:
            key = f"session:{session_id}:messages"
            messages = self.redis.lrange(key, 0, -1)
            return [json.loads(m) for m in messages]
        except Exception as e:
            logger.error(f"Redis error fetching messages: {e}")
            return []

    def add_message(self, session_id: str, role: str, content: str):
        try:
            key = f"session:{session_id}:messages"
            msg = json.dumps({"role": role, "content": content})
            self.redis.rpush(key, msg)
            self.redis.expire(key, self.ttl)
        except Exception as e:
            logger.error(f"Redis error adding message: {e}")

    def accumulate_risk(self, session_id: str, risk_score: float) -> float:
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT cumulative_risk, query_count FROM session_risk WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                
                if row:
                    new_risk = row[0] + risk_score
                    new_count = row[1] + 1
                    cursor.execute(
                        "UPDATE session_risk SET cumulative_risk = ?, query_count = ?, last_updated = ? WHERE session_id = ?",
                        (new_risk, new_count, time.time(), session_id)
                    )
                else:
                    new_risk = risk_score
                    new_count = 1
                    cursor.execute(
                        "INSERT INTO session_risk (session_id, cumulative_risk, query_count, last_updated) VALUES (?, ?, ?, ?)",
                        (session_id, new_risk, new_count, time.time())
                    )
                return new_risk
        except Exception as e:
            logger.error(f"Failed to accumulate risk for session {session_id}: {e}")
            return risk_score

    def get_risk(self, session_id: str) -> float:
        try:
            with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT cumulative_risk FROM session_risk WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                return row[0] if row else 0.0
        except Exception:
            return 0.0
