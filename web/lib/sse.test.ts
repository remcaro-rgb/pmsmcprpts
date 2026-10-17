import { describe, expect, it } from "vitest";
import { createSseParser, readSse, type SseEvent } from "./sse";

describe("createSseParser", () => {
  it("parses events split across chunks", () => {
    const events: SseEvent[] = [];
    const parse = createSseParser((e) => events.push(e));
    parse('event: text\ndata: {"text": "Hel');
    expect(events).toEqual([]);
    parse('lo"}\n\nevent: done\r\ndata: {"stop_reason": "end_turn"}\r\n\r\n');
    expect(events).toEqual([
      { event: "text", data: { text: "Hello" } },
      { event: "done", data: { stop_reason: "end_turn" } },
    ]);
  });

  it("defaults the event name and skips comment-only blocks", () => {
    const events: SseEvent[] = [];
    const parse = createSseParser((e) => events.push(e));
    parse(': keep-alive\n\ndata: {"a": 1}\n\n');
    expect(events).toEqual([{ event: "message", data: { a: 1 } }]);
  });
});

describe("readSse", () => {
  it("yields events from a byte stream", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: conversation\ndata: {"id": "c1"}\n\nevent: te'));
        controller.enqueue(encoder.encode('xt\ndata: {"text": "€"}\n\n'));
        controller.close();
      },
    });
    const events: SseEvent[] = [];
    for await (const e of readSse(body)) events.push(e);
    expect(events.map((e) => e.event)).toEqual(["conversation", "text"]);
    expect(events[1].data).toEqual({ text: "€" });
  });
});
