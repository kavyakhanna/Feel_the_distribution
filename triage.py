"""The whole mechanism.

    render  -> the ticket and account become tokens in a prompt
    sample  -> the model returns *one sample* from a distribution over outputs
    parse   -> your code turns the text back into a decision, or refuses to
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from dotenv import load_dotenv

from plumbing import fake_model, with_retries
from tickets import REFUND_CAP_NO_APPROVAL, REFUND_CAP_WITH_APPROVAL

load_dotenv()  # reads GEMINI_API_KEY (and optional GEMINI_MODEL) from .env

# The SDK logs a warning about "automatic function calling" on every plain call. We
# pass no functions, so it does not apply; keep it out of the students' terminal.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# The model matters to this lab: gemini-3.5-flash-lite accepts a temperature and ignores
# it (T=0 and T=2 return the same spread), so it cannot show you what the knob does.
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
ACTIONS = ("answer", "refund", "hold", "escalate")

# --- 1. render ----------------------------------------------------------------
# Everything the model knows about the job, the policy, and the customer is in this
# string. There is no other channel. Read it as the interface, because it is.

POLICY = f"""You are the triage step for a customer-support system. Read the ticket and the
account summary, then decide ONE action:

  answer   - resolve with information only; no money moves
  refund   - issue a refund yourself; allowed only up to ${REFUND_CAP_NO_APPROVAL}
  hold     - a refund above ${REFUND_CAP_NO_APPROVAL} and up to ${REFUND_CAP_WITH_APPROVAL}; park it for human approval
  escalate - anything above ${REFUND_CAP_WITH_APPROVAL}, anything unclear, or anything you are not sure about

Respond with a JSON object and nothing else:
  {{"action": "answer|refund|hold|escalate", "refund_amount": <number or null>, "rationale": "<one sentence>"}}
"""


def render(ticket: str, account: dict) -> str:
    """Turn the ticket and the account into the text the model will read."""
    return (
        f"{POLICY}\n"
        f"ACCOUNT SUMMARY:\n{json.dumps(account, indent=2)}\n\n"
        f"TICKET:\n{ticket}\n"
    )


# --- 2. sample ----------------------------------------------------------------

def sample(prompt: str, temperature: float | None, model: str) -> str:
    """Send the prompt once and return the raw text the model produced.

    temperature=None means "use the provider's default". Temperature is a knob on the
    softmax over the next token: 0 sharpens the distribution toward the most likely
    token, 2 flattens it. It is also only a request: the provider decides whether to
    honor it, and the only way to know is to measure, which is what Part 1 does.
    """
    from google import genai
    from google.genai import types

    client = genai.Client()  # reads GEMINI_API_KEY from the environment
    config = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json",  # a request for JSON, not a guarantee
        max_output_tokens=300,
    )
    resp = client.models.generate_content(model=model, contents=prompt, config=config)
    return resp.text or ""


# "gemini" is sample() plus patience with rate limits. "fake" is NOT a model: a stand-in
# for checking the scripts with no key. Both are in plumbing.py, which you can skip.
PROVIDERS = {"gemini": with_retries(sample), "fake": fake_model}


# --- 3. parse -----------------------------------------------------------------

def parse(raw: str) -> dict:
    """Turn the model's text into a decision, or label it malformed.

    The model can emit anything: prose, a fenced block, JSON with a typo, an action
    not in the list. None of that is an exception. It is a sample from the same
    distribution as the good answers, and it gets counted, not crashed on.
    """
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # tolerate a code fence
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {"action": "malformed", "refund_amount": None, "rationale": None}
    if not isinstance(obj, dict) or obj.get("action") not in ACTIONS:
        return {"action": "malformed", "refund_amount": None, "rationale": None}
    amount = obj.get("refund_amount")
    try:
        amount = None if amount is None else round(float(amount), 2)
    except (TypeError, ValueError):
        amount = None
    return {"action": obj["action"], "refund_amount": amount, "rationale": obj.get("rationale")}


def triage(ticket: str, account: dict, *, temperature: float | None,
           model: str = DEFAULT_MODEL, provider: str = "gemini") -> dict:
    """render -> sample -> parse. Returns one record you can write to a file."""
    prompt = render(ticket, account)
    t0 = time.perf_counter()
    raw = PROVIDERS[provider](prompt, temperature, model)
    latency_ms = round((time.perf_counter() - t0) * 1000)
    rec = parse(raw)
    rec.update({
        "model": model if provider == "gemini" else f"FAKE({model})",
        "temperature": "default" if temperature is None else temperature,
        "latency_ms": latency_ms,
        "raw": raw,
    })
    return rec
