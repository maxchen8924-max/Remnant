import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Evidence from "./Evidence";

const getEvidenceTraceMock = vi.fn();

vi.mock("../hooks/useSidecar", () => ({
  default: () => ({
    getEvidenceTrace: getEvidenceTraceMock,
    loading: false,
    error: null,
  }),
}));

describe("Evidence page", () => {
  beforeEach(() => {
    getEvidenceTraceMock.mockReset();
  });

  it("loads trace evidence by trace id", async () => {
    getEvidenceTraceMock.mockResolvedValue({
      trace_id: "trace-123",
      scope_id: "scope-a",
      query_text: "tea",
      duration_ms: 12,
      result_counts: {
        fts: 0,
        vector: 0,
        reranked: 1,
      },
      evidence_count: 1,
      evidences: [
        {
          rank: 1,
          chunk_id: "chunk-1",
          chunk_type: "conversation_segment",
          source: "keyword_fallback",
          combined_score: 0.35,
          content: "dad liked tea every afternoon",
          source_artifact: {
            artifact_id: "artifact-1",
            file_type: "universal_chat_json",
            file_hash: "hash-abc",
            source_path_status: "redacted",
          },
          spans: [],
        },
      ],
    });

    render(<Evidence />);

    fireEvent.change(screen.getByLabelText("Trace ID"), {
      target: { value: "trace-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "加载证据" }));

    await waitFor(() => {
      expect(getEvidenceTraceMock).toHaveBeenCalledWith("trace-123");
    });

    expect(await screen.findByText("trace-123")).toBeInTheDocument();
    expect(screen.getByText("scope-a")).toBeInTheDocument();
    expect(screen.getByText("tea")).toBeInTheDocument();
    expect(screen.getByText("dad liked tea every afternoon")).toBeInTheDocument();
    expect(screen.getByText("universal_chat_json")).toBeInTheDocument();
    expect(screen.getByText("redacted")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Evidence cards")).getByText("chunk-1")).toBeInTheDocument();
  });

  it("requires a trace id before loading evidence", () => {
    render(<Evidence />);

    fireEvent.click(screen.getByRole("button", { name: "加载证据" }));

    expect(screen.getByText("Trace ID 必填。")).toBeInTheDocument();
    expect(getEvidenceTraceMock).not.toHaveBeenCalled();
  });
});
