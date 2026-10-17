"""Transcript parsers: turn an agent's raw event log into an AgentRun.

Agents change their output formats often, so each parser is a set of small
pure functions over plain dicts (the same dicts we save as the transcript).
Tests feed them recorded transcripts; no API calls needed.
"""
