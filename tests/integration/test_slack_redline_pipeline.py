"""Live integration test — Slack mention → Oscar → 10P pipeline → Slack reply.

Marked ``@pytest.mark.live`` and gated behind the ``--live-integration``
flag plus the presence of OSCAR_LLM_OSCAR_*, OSCAR_LLM_REDLINE_PLANNER_*,
OSCAR_LLM_REDLINE_EXECUTOR_*, OSCAR_SLACK_BOT_TOKEN, and
OSCAR_SLACK_APP_TOKEN in ``/etc/oscar/oscar.env``. Real LLMs, real Slack,
real .docx output. Per CLAUDE.md "No Cheating on Pipeline Tests".

Run at sprint close::

    pytest tests/integration/test_slack_redline_pipeline.py \\
        --live-integration -v -s

The test sends a Slack mention to ``#oscar-test`` from a workspace user,
waits up to 180s for replies in the thread, and asserts:

  1. An acknowledgement message lands within 3 seconds of the mention.
  2. At least three progress-narration messages arrive over the
     pipeline window (55-128s).
  3. A final completion message references the output path.
  4. The output ``.docx`` is on disk with valid two-author tracked-
     change shape (uses ``verify_output`` from 10P's ``run.py``).

The 10P fixture path is hardcoded — Slack file upload (M4) replaces it
with attachment-derived paths.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

# The ``--live-integration`` flag is registered in ``tests/conftest.py``
# (session-level) so it survives plugin collection edge cases.


def _live_credentials_present() -> bool:
    """All env vars and the input fixture must be on disk for the test to run."""
    required_env = (
        "OSCAR_LLM_OSCAR_PROVIDER",
        "OSCAR_LLM_OSCAR_MODEL",
        "OSCAR_LLM_OSCAR_API_KEY",
        "OSCAR_LLM_REDLINE_PLANNER_PROVIDER",
        "OSCAR_LLM_REDLINE_PLANNER_MODEL",
        "OSCAR_LLM_REDLINE_PLANNER_API_KEY",
        "OSCAR_LLM_REDLINE_EXECUTOR_PROVIDER",
        "OSCAR_LLM_REDLINE_EXECUTOR_MODEL",
        "OSCAR_LLM_REDLINE_EXECUTOR_API_KEY",
        "OSCAR_SLACK_BOT_TOKEN",
        "OSCAR_SLACK_APP_TOKEN",
        "OSCAR_TEST_SLACK_USER_TOKEN",  # workspace user token for the test bot
        "OSCAR_TEST_SLACK_CHANNEL_ID",  # the test channel id (e.g. C0123)
    )
    return all(os.environ.get(name) for name in required_env)


pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def _require_live_flag(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--live-integration", default=False):
        pytest.skip("live integration test — pass --live-integration to run")
    if not _live_credentials_present():
        pytest.skip(
            "live integration test — required env vars missing; populate "
            "/etc/oscar/oscar.env per docs/sprints/M3-preflight.md § 3"
        )


@pytest.mark.asyncio
async def test_slack_mention_produces_redlined_docx_with_progress() -> None:
    """The end-to-end live test for M3 sprint close.

    Drives a Slack mention through Oscar and asserts the four pipeline
    contracts (ack < 3s, ≥3 progress messages, final completion message,
    output .docx valid). Marked live; skipped without credentials.
    """
    from shared.runtime.main import run

    # Local imports — slack_sdk is heavy and the unit suite shouldn't
    # take the import-time hit when this test is skipped.
    from slack_sdk.web.async_client import AsyncWebClient

    # Bring 10P's verify_output onto the path so we can validate the
    # output .docx without running the whole pipeline again.
    repo_root = Path(__file__).resolve().parents[2]
    tenp_dir = repo_root / "src/redline/experiments/sprint-10P"
    if str(tenp_dir) not in sys.path:
        sys.path.insert(0, str(tenp_dir))
    import importlib

    run_module = importlib.import_module("run")
    verify_output = run_module.verify_output

    output_path = repo_root / "src/redline/experiments/sprint-10P/nda-output-oscar.docx"
    if output_path.exists():
        output_path.unlink()  # ensure we observe a fresh write

    user_token = os.environ["OSCAR_TEST_SLACK_USER_TOKEN"]
    channel_id = os.environ["OSCAR_TEST_SLACK_CHANNEL_ID"]
    user_client = AsyncWebClient(token=user_token)

    stop_event = asyncio.Event()
    runtime_task = asyncio.create_task(run(stop_event=stop_event))

    try:
        # Wait briefly for the runtime to come up (Socket Mode handshake).
        await asyncio.sleep(3.0)

        sent = await user_client.chat_postMessage(
            channel=channel_id,
            text=(
                "<@OSCAR_BOT> Please review the attached Zenith redlines on "
                "the Acme NDA — fixture-path test."
            ),
        )
        thread_ts = sent["ts"]
        sent_at = time.monotonic()

        # Poll the thread until we see the final completion message or
        # 180 seconds elapse (10P pipeline is 55-128s).
        deadline = sent_at + 180.0
        replies: list[dict] = []
        ack_within_3s = False
        while time.monotonic() < deadline:
            resp = await user_client.conversations_replies(
                channel=channel_id, ts=thread_ts
            )
            replies = resp.get("messages", [])[1:]  # exclude the user's own
            if replies and not ack_within_3s:
                first_reply_at = float(replies[0]["ts"])
                if first_reply_at - float(thread_ts) <= 3.0:
                    ack_within_3s = True
            if any("output" in (m.get("text") or "").lower() for m in replies):
                break
            await asyncio.sleep(2.0)

        # Assertions.
        assert replies, "no replies arrived in the thread within 180s"
        assert ack_within_3s, (
            "first reply did not arrive within 3 seconds — Slack ack "
            "window violated (ADR 028 progress-narration design)"
        )
        assert len(replies) >= 4, (
            f"expected at least 4 messages (≥3 progress + final); got "
            f"{len(replies)}: {[m.get('text', '')[:80] for m in replies]}"
        )
        assert any(
            "output" in (m.get("text") or "").lower() for m in replies
        ), "no completion message references the output path"

        # Output .docx is on disk and has the expected shape.
        assert output_path.exists(), f"output .docx not written: {output_path}"
        ok, notes = verify_output(output_path)
        assert ok, f"verify_output failed; notes:\n  " + "\n  ".join(notes)
    finally:
        stop_event.set()
        await asyncio.wait_for(runtime_task, timeout=30.0)
