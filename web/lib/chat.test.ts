import { describe, expect, it } from "vitest";
import { applyEvent, httpErrorMessage, isTableResult, type AssistantMessage } from "./chat";

const empty = (): AssistantMessage => ({ role: "assistant", id: "a1", parts: [], status: "streaming" });

function run(events: [string, unknown][]): AssistantMessage {
  return events.reduce((m, [event, data]) => applyEvent(m, { event, data }), empty());
}

describe("applyEvent", () => {
  it("builds parts in stream order, merging consecutive deltas", () => {
    const table = { dataset_id: "ds_1", columns: [{ name: "n", type: "int8" }], rows: [[1]], row_count: 1 };
    const m = run([
      ["thinking", { text: "Need " }],
      ["thinking", { text: "KPIs." }],
      ["tool_start", { id: "t1", name: "get_kpis" }],
      ["tool_call", { id: "t1", name: "get_kpis", input: { start: "2026-07-01" } }],
      ["tool_result", { id: "t1", name: "get_kpis", is_error: false, result: table }],
      ["text", { text: "Occupancy " }],
      ["text", { text: "was high." }],
      ["done", { stop_reason: "end_turn", usage: { input_tokens: 10, output_tokens: 5 } }],
    ]);
    expect(m.status).toBe("done");
    expect(m.usage?.output_tokens).toBe(5);
    expect(m.parts).toEqual([
      { kind: "thinking", text: "Need KPIs." },
      { kind: "tool", id: "t1", name: "get_kpis", status: "done", input: { start: "2026-07-01" }, result: table },
      { kind: "text", text: "Occupancy was high." },
    ]);
  });

  it("tracks parallel tool calls and failures independently", () => {
    const m = run([
      ["tool_start", { id: "t1", name: "run_sql" }],
      ["tool_start", { id: "t2", name: "run_sql" }],
      ["tool_result", { id: "t2", name: "run_sql", is_error: true, result: "bad column" }],
    ]);
    expect(m.parts.map((p) => p.kind === "tool" && p.status)).toEqual(["running", "error"]);
  });

  it("records refusals and errors", () => {
    expect(run([["refusal", { message: "Declined." }]])).toMatchObject({ status: "refused", error: "Declined." });
    expect(run([["error", { message: "Boom" }]])).toMatchObject({ status: "error", error: "Boom" });
  });
});

describe("helpers", () => {
  it("recognizes table results", () => {
    expect(isTableResult({ columns: [], rows: [] })).toBe(true);
    expect(isTableResult({ relations: [] })).toBe(false);
    expect(isTableResult("text")).toBe(false);
  });

  it("formats HTTP errors from the agent", () => {
    expect(httpErrorMessage(409, '{"detail": "Busy."}')).toBe("Busy.");
    expect(httpErrorMessage(422, '{"detail": [{"msg": "too short"}]}')).toBe("too short");
    expect(httpErrorMessage(502, "<html>")).toBe("Request failed (502).");
  });
});
