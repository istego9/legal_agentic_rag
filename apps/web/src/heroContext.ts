export type HeroActiveContextKey = "workspaceDocuments" | "workspaceGold" | "workspaceToolOps";

export function resolveHeroActiveContextKey(
  workspaceSection: "documents" | "gold",
  isOpsInternalToolActive: boolean
): HeroActiveContextKey {
  if (isOpsInternalToolActive) {
    return "workspaceToolOps";
  }
  return workspaceSection === "documents" ? "workspaceDocuments" : "workspaceGold";
}
