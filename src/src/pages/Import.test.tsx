import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Import from "./Import";

const importDataMock = vi.fn();
const resolveProfileMock = vi.fn();

vi.mock("../hooks/useSidecar", () => ({
  default: () => ({
    importData: importDataMock,
    resolveProfile: resolveProfileMock,
    loading: false,
    error: null,
  }),
}));

describe("Import page", () => {
  beforeEach(() => {
    importDataMock.mockReset();
    resolveProfileMock.mockReset();
  });

  it("imports a universal chat file and renders import metrics", async () => {
    resolveProfileMock.mockResolvedValue({
      deceased_profile_id: "profile-001",
      profile_name: "妈妈",
      created: true,
    });
    importDataMock.mockResolvedValue({
      artifact_id: "artifact-123",
      file_hash: "hash-abc",
      message_count: 18,
      chunk_count: 6,
      parse_status: "ok",
      errors: [],
    });

    render(<Import />);

    fireEvent.change(screen.getByLabelText("逝者档案"), {
      target: { value: "妈妈" },
    });
    fireEvent.change(screen.getByLabelText("本地文件路径"), {
      target: { value: "/tmp/universal-chat.json" },
    });
    fireEvent.change(screen.getByLabelText("记忆空间"), {
      target: { value: "scope-family" },
    });
    fireEvent.click(screen.getByRole("button", { name: "开始导入" }));

    await waitFor(() => {
      expect(resolveProfileMock).toHaveBeenCalledWith({
        profile_name: "妈妈",
      });
      expect(importDataMock).toHaveBeenCalledWith({
        deceased_profile_id: "profile-001",
        file_path: "/tmp/universal-chat.json",
        file_type: "universal_chat_json",
        scope_id: "scope-family",
        encoding: "utf-8",
        metadata: {
          source_adapter: "universal_chat_json",
          source_adapter_label: "Universal Chat JSON",
          profile_name: "妈妈",
        },
      });
    });

    expect(await screen.findByText("artifact-123")).toBeInTheDocument();
    expect(screen.getByText("18")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.getByText("hash-abc")).toBeInTheDocument();
  });

  it("validates required profile and file path before importing", () => {
    render(<Import />);

    fireEvent.click(screen.getByRole("button", { name: "开始导入" }));

    expect(screen.getByText("逝者档案必填。")).toBeInTheDocument();
    expect(screen.getByText("本地文件路径必填。")).toBeInTheDocument();
    expect(importDataMock).not.toHaveBeenCalled();
  });

  it("offers global chat adapters instead of a WeChat-only import", () => {
    render(<Import />);

    expect(screen.getByRole("option", { name: /Universal Chat JSON/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /WeChat TXT/ })).toBeInTheDocument();
  });
});
