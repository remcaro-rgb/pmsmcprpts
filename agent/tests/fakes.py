"""A scripted stand-in for anthropic.AsyncAnthropic's streaming beta Messages API."""

import copy
from types import SimpleNamespace

from anthropic.types.beta import BetaTextBlock, BetaThinkingBlock, BetaToolUseBlock


def usage():
    return SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=80,
                           cache_creation_input_tokens=0)


class FakeStream:
    def __init__(self, content, stop_reason, events, stop_details=None, error=None):
        self.message = SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage(),
                                       stop_details=stop_details)
        self.events = events
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _iter(self):
        for e in self.events:
            yield e
        if self.error:
            raise self.error

    def __aiter__(self):
        return self._iter()

    async def get_final_message(self):
        return self.message


def text_reply(text, stop_reason="end_turn"):
    return FakeStream([BetaTextBlock(type="text", text=text)], stop_reason,
                      [SimpleNamespace(type="text", text=text)])


def tool_calls(*calls, thinking="Need data.", stop_reason="tool_use"):
    """calls: (id, name, input) tuples."""
    content = [BetaThinkingBlock(type="thinking", thinking=thinking, signature="sig")]
    events = [SimpleNamespace(type="thinking", thinking=thinking)]
    for id_, name, input_ in calls:
        content.append(BetaToolUseBlock(type="tool_use", id=id_, name=name, input=input_))
        events.append(SimpleNamespace(type="content_block_start",
                                      content_block=SimpleNamespace(type="tool_use", id=id_, name=name)))
    return FakeStream(content, stop_reason, events)


def refusal(category="cyber"):
    return FakeStream([], "refusal", [], stop_details=SimpleNamespace(category=category))


class FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def stream(self, **params):
        self.requests.append(copy.deepcopy(params))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, *script):
        self.messages = FakeMessages(script)
        self.beta = SimpleNamespace(messages=self.messages)
