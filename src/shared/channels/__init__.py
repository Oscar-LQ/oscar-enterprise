"""Channel framework: inbound user messages and outbound replies.

Phase 1 (Sprint M2) defines the minimum Channel Protocol + InboundMessage
shape and ships a FakeChannel for tests. Phase 2 adds Slack (Socket Mode,
under slack/) and AgentMail (WebSocket, under agentmail/) as separate
implementations with no shared files between them — the Protocol is the
only seam they share.

The Protocol is deliberately small (start, stop, post_message,
on_inbound_message). Methods are added in subsequent sprints when a
concrete channel surfaces a need that the dispatcher cannot serve against
the current surface (ADR 023).
"""
