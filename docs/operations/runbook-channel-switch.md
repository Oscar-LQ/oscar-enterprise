# Runbook: switching channels

This runbook documents the FakeChannel-as-substitute pattern that makes Oscar's runtime channel-swappable without code changes to the dispatcher or the GC. Seeded in Sprint M2 Phase 1; expanded in Phase 3 once the runtime entry point lands.

## When you'd use this

- **Local development without Slack credentials** — stand up the GC with FakeChannel; drive it from a Python REPL or a test script via `simulate_inbound()`.
- **CI integration tests** — exercise the dispatcher → GC round-trip without hitting Slack or AgentMail; FakeChannel records outbound posts for assertions.
- **Diagnosing a misbehaving live channel** — swap the live channel for FakeChannel to confirm the bug is on the channel side rather than in the dispatcher / GC.

## How

The Channel Protocol is the seam (`src/shared/channels/base.py`). All concrete implementations — `FakeChannel`, `SlackChannel` (Phase 2A), `AgentMailChannel` (Phase 2B) — are interchangeable from the dispatcher's perspective.

```python
from shared.agents.general_counsel import build_general_counsel
from shared.channels.base import InboundMessage
from shared.channels.fake import FakeChannel
from shared.dispatcher import Dispatcher

channel = FakeChannel()
gc = build_general_counsel()  # MemorySaver checkpointer wired at build time
dispatcher = Dispatcher(channel=channel, gc_graph=gc)
channel.on_inbound_message(dispatcher.handle)

await channel.start()
await channel.simulate_inbound(
    InboundMessage(conversation_id="local:dev", text="hello GC")
)
print(channel.posted_messages)   # [PostedMessage(conversation_id='local:dev', text=...)]
await channel.stop()
```

Replace the first three lines with the Phase 2 channel of choice (e.g. `SlackChannel.from_env()` or `AgentMailChannel.from_env()`) and the rest is unchanged.

## What `FakeChannel` does (and doesn't do)

- **Does** — record outbound `post_message` calls in `posted_messages`; route `simulate_inbound(message)` to the registered dispatcher handler.
- **Does not** — exercise any external network; validate channel-id formats; enforce rate limits or thread-locking semantics that the real channel might.

For end-to-end behaviour against a real channel, see Phase 3 integration tests (M2 spec § Tests; `docs/sprints/M2-spec.md`).

## To be expanded in Phase 3

- A `make local-channel` (or equivalent) target that boots the runtime with FakeChannel + an interactive REPL.
- Notes on swap-in-place tactics for diagnosing live-channel issues without restarting the runtime mid-conversation.
