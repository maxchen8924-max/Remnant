import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ScopeCreate from "./ScopeCreate";

const createScopeMock = vi.fn();
const resolveProfileMock = vi.fn();
const navigateMock = vi.fn();

vi.mock("../hooks/useSidecar", () => ({
  default: () => ({
    createScope: createScopeMock,
    resolveProfile: resolveProfileMock,
    loading: false,
    error: null,
  }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

describe("ScopeCreate page", () => {
  beforeEach(() => {
    createScopeMock.mockReset();
    resolveProfileMock.mockReset();
    navigateMock.mockReset();
  });

  it("creates a scope from a user-facing profile name", async () => {
    resolveProfileMock.mockResolvedValue({
      deceased_profile_id: "profile-001",
      profile_name: "妈妈",
      created: false,
    });
    createScopeMock.mockResolvedValue({
      scope_id: "scope-001",
      status: "created",
    });

    render(<ScopeCreate />);

    fireEvent.change(screen.getByLabelText(/逝者档案名称/), {
      target: { value: "妈妈" },
    });
    fireEvent.change(screen.getByLabelText(/关系空间名称/), {
      target: { value: "作为女儿" },
    });
    fireEvent.change(screen.getByLabelText(/关系类型/), {
      target: { value: "child" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建关系空间" }));

    await waitFor(() => {
      expect(resolveProfileMock).toHaveBeenCalledWith({
        profile_name: "妈妈",
      });
      expect(createScopeMock).toHaveBeenCalledWith({
        deceased_profile_id: "profile-001",
        scope_name: "作为女儿",
        relationship_type: "child",
        scope_description: undefined,
      });
    });
  });
});
