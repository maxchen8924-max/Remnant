import type { JsonValue } from "../hooks/useSidecar";

export interface RelationshipSpace {
  id: string;
  scope_name: string;
  relationship_type: string;
  scope_description?: string;
}

const RELATIONSHIP_LABELS: Record<string, string> = {
  spouse: "配偶",
  child: "子女",
  sibling: "兄弟姐妹",
  parent: "父母",
  friend: "朋友",
  colleague: "同事",
  other: "其他",
};

export function getProfileId(value: JsonValue): string {
  const record = asRecord(value);
  if (!record || typeof record.deceased_profile_id !== "string" || !record.deceased_profile_id) {
    throw new Error("无法解析逝者档案。");
  }

  return record.deceased_profile_id;
}

export function getRelationshipSpaces(value: JsonValue): RelationshipSpace[] {
  const record = asRecord(value);
  if (!record || !Array.isArray(record.scopes)) {
    return [];
  }

  return record.scopes.flatMap((item) => {
    const scope = asRecord(item);
    if (!scope || typeof scope.id !== "string" || typeof scope.scope_name !== "string") {
      return [];
    }

    return [
      {
        id: scope.id,
        scope_name: scope.scope_name,
        relationship_type:
          typeof scope.relationship_type === "string" ? scope.relationship_type : "other",
        scope_description:
          typeof scope.scope_description === "string" ? scope.scope_description : undefined,
      },
    ];
  });
}

export function formatRelationshipSpaceLabel(space: RelationshipSpace): string {
  const relationshipLabel = RELATIONSHIP_LABELS[space.relationship_type] || space.relationship_type;
  return `${space.scope_name} (${relationshipLabel})`;
}

function asRecord(value: JsonValue): Record<string, JsonValue> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  return value as Record<string, JsonValue>;
}
