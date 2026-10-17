export type SseEvent = { event: string; data: unknown };

/** Incremental parser for a text/event-stream body. Feed it chunks; it calls onEvent per event. */
export function createSseParser(onEvent: (event: SseEvent) => void) {
  let buffer = "";
  return (chunk: string) => {
    buffer += chunk.replace(/\r\n?/g, "\n");
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length) onEvent({ event, data: JSON.parse(data.join("\n")) });
    }
  };
}

/** Yields the events of a server-sent-events response body as they arrive. */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const queue: SseEvent[] = [];
  const parse = createSseParser((e) => queue.push(e));
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parse(decoder.decode(value, { stream: true }));
      while (queue.length) yield queue.shift()!;
    }
  } finally {
    reader.releaseLock();
  }
}
