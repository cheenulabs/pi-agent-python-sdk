// Pure protocol projection: upstream owns the bounded/coalesced watch window.
export function nextWatchUpdate<T extends { readonly id: number }>(
  lastSentId: number | undefined,
  entries: readonly T[],
): { entries: T[]; gap: boolean } {
  return {
    entries: entries.filter((entry) => lastSentId === undefined || entry.id > lastSentId),
    gap: lastSentId !== undefined && entries.length > 0 &&
      !entries.some((entry) => entry.id === lastSentId),
  };
}
