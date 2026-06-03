import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Query from "./Query";

const queryMock = vi.fn();

vi.mock("../hooks/useSidecar", () => ({
  default: () => ({
    query: queryMock,
    loading: false,
    error: null,
  }),
}));

describe("Query page", () => {
  beforeEach(() => {
    queryMock.mockReset();
  });

  it("runs a scoped query and renders answer, trace, and evidence rows", async () => {
    queryMock.mockResolvedValue({
      content:
        "Evidence-backed memory summary:\n" +
        "1. [妈妈] 春天到了，我打算周末去西湖看看 [keyword_fallback, score=0.35]\n" +
        "No persona generation was performed; this is a retrieval summary.",
      retrieval_trace_id: "trace-123",
      duration_ms: 42,
      safety_flags: [],
    });

    render(<Query />);

    fireEvent.change(screen.getByLabelText("Scope ID"), {
      target: { value: "scope-abc" },
    });
    fireEvent.change(screen.getByLabelText("问题"), {
      target: { value: "西湖" },
    });
    fireEvent.click(screen.getByRole("button", { name: "查询证据" }));

    await waitFor(() => {
      expect(queryMock).toHaveBeenCalledWith({
        scope_id: "scope-abc",
        query: "西湖",
        stream: false,
      });
    });

    expect(await screen.findByText("trace-123")).toBeInTheDocument();
    expect(screen.getByText(/Evidence-backed memory summary/)).toBeInTheDocument();
    expect(within(screen.getByLabelText("Evidence rows")).getByText(/春天到了/)).toBeInTheDocument();
    expect(screen.getByText("42 ms")).toBeInTheDocument();
  });

  it("keeps unanswered queries evidence-bounded", async () => {
    queryMock.mockResolvedValue({
      content:
        "No matching evidence was found in the selected relationship scope. " +
        "I cannot answer this as a factual memory yet.",
      retrieval_trace_id: null,
      duration_ms: 9,
      safety_flags: ["scope_not_found"],
    });

    render(<Query />);

    fireEvent.change(screen.getByLabelText("Scope ID"), {
      target: { value: "missing-scope" },
    });
    fireEvent.change(screen.getByLabelText("问题"), {
      target: { value: "没有证据的问题" },
    });
    fireEvent.click(screen.getByRole("button", { name: "查询证据" }));

    expect(await screen.findByText("无 trace")).toBeInTheDocument();
    expect(screen.getByText(/No matching evidence was found/)).toBeInTheDocument();
    expect(screen.getByText("scope_not_found")).toBeInTheDocument();
  });
});
