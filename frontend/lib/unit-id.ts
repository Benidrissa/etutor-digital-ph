export function legacyUnitIdToUnitNumber(unitId: string): string | null {
  const m = unitId.match(/^M0*(\d+)-U0*(\d+)$/);
  return m ? `${m[1]}.${m[2]}` : null;
}

export function matchUnit<T extends { id: string; unit_number: string }>(
  units: T[] | undefined,
  unitId: string,
): T | undefined {
  if (!units) return undefined;
  const legacy = legacyUnitIdToUnitNumber(unitId);
  return units.find(
    (u) =>
      u.id === unitId ||
      u.unit_number === unitId ||
      (legacy !== null && u.unit_number === legacy),
  );
}
