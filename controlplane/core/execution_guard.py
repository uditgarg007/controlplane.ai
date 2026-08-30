from typing import Any, Dict, List
import re
from loguru import logger
from controlplane.config import SeverityLevel

class ExecutionGuard:
    """
    Validates agentic tool calls against security policies.
    """
    # Block list for potentially destructive or dangerous commands
    DANGEROUS_COMMANDS = [
        r"^rm\s+-rf",
        r"^drop\s+(table|database)",
        r"^truncate\s+table",
        r"^delete\s+from",
        r"^eval\s*\(",
        r"^exec\s*\(",
        r"^os\.system",
        r"^subprocess\.",
    ]

    # Allowed domains for network requests
    ALLOWED_DOMAINS = [
        "api.github.com",
        "api.stripe.com",
        "controlplane.ai",
        "localhost",
        "127.0.0.1",
    ]

    @classmethod
    def validate_tool_call(cls, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates if a tool execution request is safe.
        Returns a dict with 'allowed', 'reason', and 'severity'.
        """
        logger.info(f"[ExecutionGuard] Validating tool {tool_name} with args {args}")

        # Rule 1: Check for dangerous commands (e.g., if it's a bash/sql tool)
        if tool_name in ["run_bash", "execute_sql", "python_eval"]:
            command = str(args.get("command", "") or args.get("query", "") or args.get("code", ""))
            for pattern in cls.DANGEROUS_COMMANDS:
                if re.search(pattern, command, re.IGNORECASE):
                    logger.warning(f"[ExecutionGuard] Blocked {tool_name} due to dangerous pattern: {pattern}")
                    return {
                        "allowed": False,
                        "reason": "Destructive or high-risk command detected.",
                        "severity": SeverityLevel.FAIL
                    }

        # Rule 2: Check for unauthorized network requests
        if tool_name in ["fetch_url", "http_request", "download_file"]:
            url = str(args.get("url", ""))
            domain = cls._extract_domain(url)
            if domain and domain not in cls.ALLOWED_DOMAINS:
                logger.warning(f"[ExecutionGuard] Blocked {tool_name} to unauthorized domain: {domain}")
                return {
                    "allowed": False,
                    "reason": f"Network request to unauthorized domain: {domain}",
                    "severity": SeverityLevel.FAIL
                }

        return {
            "allowed": True,
            "reason": "Execution approved by guardrails.",
            "severity": SeverityLevel.PASS
        }

    @staticmethod
    def _extract_domain(url: str) -> str:
        match = re.match(r"https?://([^/]+)", url)
        if match:
            return match.group(1).split(":")[0]  # remove port if exists
        return ""
