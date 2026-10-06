"""Optional local LLM rewrite through Ollama (PRD §9 step 3). Never required.

When ``REPORT_ENGINE=ollama`` and ``SCOUT_OLLAMA_MODEL`` names a locally pulled model, the
template report is sent to the local Ollama server with an instruction to improve fluency
without adding facts, at low temperature and with a fixed seed. The answer is only used if
it passes the grounding validator; any error (server down, timeout, empty answer) returns
``None`` and the caller keeps the template report. Only the local server is ever called.
"""

from __future__ import annotations

import logging

import httpx

from scout.config import OllamaConfig

logger = logging.getLogger(__name__)

PROMPT = """You are editing a football scouting report. Rewrite it so it reads fluently
for a club's technical director. Rules:
- Use only the facts in the report. Do not add any number, name, club, date or claim.
- Keep every number exactly as written, with its unit.
- Keep the section headings and their order.
- Keep the caveats.
- Plain text only.

REPORT:
{report}

REWRITTEN REPORT:
"""


def rewrite(
    report: str,
    *,
    model: str,
    cfg: OllamaConfig,
    seed: int,
    client: httpx.Client | None = None,
) -> str | None:
    """Ask the local Ollama server to rewrite ``report``; ``None`` on any failure."""
    url = cfg.base_url.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "prompt": PROMPT.format(report=report),
        "stream": False,
        "options": {"temperature": cfg.temperature, "seed": seed},
    }
    owns_client = client is None
    http = client or httpx.Client(timeout=cfg.timeout_seconds)
    try:
        response = http.post(url, json=payload)
        response.raise_for_status()
        text = response.json().get("response")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("ollama rewrite failed", extra={"error": str(exc), "model": model})
        return None
    finally:
        if owns_client:
            http.close()
    if not isinstance(text, str) or not text.strip():
        logger.warning("ollama returned no text", extra={"model": model})
        return None
    return text.strip() + "\n"
