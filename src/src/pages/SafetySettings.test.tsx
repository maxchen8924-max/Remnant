import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SafetySettings from "./SafetySettings";

const resolveProfileMock = vi.fn();
const listScopesMock = vi.fn();
const getSafetyPolicyMock = vi.fn();
const updateSafetyPolicyMock = vi.fn();
const getSafetyEventsMock = vi.fn();

vi.mock("../hooks/useSidecar", () => ({
  default: () => ({
    resolveProfile: resolveProfileMock,
    listScopes: listScopesMock,
    getSafetyPolicy: getSafetyPolicyMock,
    updateSafetyPolicy: updateSafetyPolicyMock,
    getSafetyEvents: getSafetyEventsMock,
    loading: false,
    error: null,
  }),
}));

describe("SafetySettings page", () => {
  beforeEach(() => {
    resolveProfileMock.mockReset();
    listScopesMock.mockReset();
    getSafetyPolicyMock.mockReset();
    updateSafetyPolicyMock.mockReset();
    getSafetyEventsMock.mockReset();
  });

  it("loads safety policy by selecting a relationship space from a profile name", async () => {
    resolveProfileMock.mockResolvedValue({
      deceased_profile_id: "profile-001",
      profile_name: "妈妈",
      created: false,
    });
    listScopesMock.mockResolvedValue({
      scopes: [
        {
          id: "scope-safe",
          scope_name: "家人空间",
          relationship_type: "child",
        },
      ],
    });
    getSafetyPolicyMock.mockResolvedValue({
      safety_policy: {
        max_session_minutes: 45,
        hard_break_enabled: false,
      },
    });
    getSafetyEventsMock.mockResolvedValue({ events: [] });

    render(<SafetySettings />);

    fireEvent.change(screen.getByLabelText("逝者档案"), {
      target: { value: "妈妈" },
    });
    fireEvent.click(screen.getByRole("button", { name: "加载关系空间" }));

    expect(await screen.findByRole("option", { name: /家人空间/ })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("关系空间"), {
      target: { value: "scope-safe" },
    });
    fireEvent.click(screen.getByRole("button", { name: "加载安全策略" }));

    await waitFor(() => {
      expect(resolveProfileMock).toHaveBeenCalledWith({
        profile_name: "妈妈",
      });
      expect(listScopesMock).toHaveBeenCalledWith("profile-001");
      expect(getSafetyPolicyMock).toHaveBeenCalledWith("scope-safe");
      expect(getSafetyEventsMock).toHaveBeenCalledWith("scope-safe", 7);
    });

    expect(screen.getByText("关系空间: 家人空间")).toBeInTheDocument();
    expect(screen.getByDisplayValue("45")).toBeInTheDocument();
  });

  it("validates the profile name before loading relationship spaces", () => {
    render(<SafetySettings />);

    fireEvent.click(screen.getByRole("button", { name: "加载关系空间" }));

    expect(screen.getByText("逝者档案必填。")).toBeInTheDocument();
    expect(resolveProfileMock).not.toHaveBeenCalled();
  });
});
