"""Plumbing. Not the mechanism: you do not need to read this file to do the lab.

Two things live here so that triage.py can stay short enough to read in one sitting:
retrying when the provider says "slow down", and a fake provider for checking the
scripts with no key.
"""
from __future__ import annotations

import json
import random
import time


def with_retries(sample):
    """Wrap a sample(prompt, temperature, model) function so a run finishes.

    The free tier *is* a per-minute rate limit: a 429 means "the minute is not over
    yet", so sleep briefly and try again. A daily cap, a billing problem, or a provider
    that keeps returning 5xx will not get better by waiting, so stop and say why.
    """
    def call(prompt: str, temperature: float | None, model: str) -> str:
        from google.genai import errors

        switch = ("Set GEMINI_MODEL in .env to another free-tier model (for example "
                  "gemini-2.5-flash-lite) and rerun; a saved run replays with --replay.")
        delay, server_errors = 5, 0
        for _ in range(30):
            try:
                return sample(prompt, temperature, model)
            except errors.ClientError as e:
                if e.code != 429:
                    raise
                msg = getattr(e, "message", str(e))
                if any(w in msg.lower() for w in ("day", "depleted", "billing", "credits")):
                    raise SystemExit(f"\n{model} refused: {msg[:200]}\n{switch}")
                print(f"    rate limited; sleeping {delay}s", flush=True)
                time.sleep(delay)
            except errors.ServerError as e:
                server_errors += 1
                if server_errors == 1:
                    print(f"    server error {e.code}: {getattr(e, 'message', str(e))[:120]}", flush=True)
                if server_errors >= 5:
                    raise SystemExit(f"\n{model} keeps returning {e.code}; that is the provider, not you. {switch}")
                print(f"    retrying in {delay}s", flush=True)
                time.sleep(delay)
        raise SystemExit(f"\nGave up after repeated rate limits on {model}. {switch}")
    return call


def fake_model(prompt: str, temperature: float | None, model: str) -> str:
    """NOT a model. A stand-in that samples from a made-up distribution so you can check
    the plumbing (parsing, plotting, tables) with no key and no quota. Any conclusion
    you draw from fake output is a conclusion about this function, not about a model.
    """
    t = 1.0 if temperature is None else temperature
    amounts = [52.99]  # the fixed ticket: lamp plus shipping
    if "SYSTEM OVERRIDE" in prompt:
        weights = {"answer": 0, "refund": 9, "hold": 0, "escalate": 1}; amounts = [480]
    elif "pre-approved" in prompt:
        weights = {"answer": 0, "refund": 1, "hold": 0, "escalate": 9}; amounts = [480]
    elif "$88" in prompt:
        weights = {"answer": 0, "refund": 0, "hold": 1, "escalate": 0}; amounts = [88]
    elif "$34" in prompt:
        weights = {"answer": 0, "refund": 9, "hold": 1, "escalate": 0}; amounts = [34]
    elif any(w in prompt.lower() for w in ("password", "log in", "locked out", "where is", "tracking")):
        weights = {"answer": 19, "refund": 0, "hold": 0, "escalate": 1}
    else:  # the ambiguous fixed ticket
        weights = {"answer": 0, "refund": 1, "hold": 19, "escalate": 0}
        if t > 1:  # flatten: the decision and the amount both start to move
            weights = {"answer": 0, "refund": 4, "hold": 6, "escalate": 0}
            amounts = [52.99, 52.99, 52.99, 50, 50, 67.99]
    if t == 0:  # sharpen all the way to the mode
        mode = max(weights, key=weights.get)
        weights = {k: int(k == mode) for k in weights}
        amounts = amounts[:1]
    action = random.choices(list(weights), weights=list(weights.values()))[0]
    amount = None
    if action in ("refund", "hold"):
        amount = random.choice(amounts)
    if random.random() < 0.03:
        return "Sure! Here is my decision: refund the lamp."  # malformed on purpose
    return json.dumps({"action": action, "refund_amount": amount, "rationale": "fake"})
