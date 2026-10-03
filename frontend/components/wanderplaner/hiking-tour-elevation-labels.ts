// Beschriftungen nahe an der Kurve halten und nur bei Kollisionen anheben.
export function layoutElevationLabels(labels: { x: number; width: number; y?: number }[], chartWidth: number) {
  const occupied: { left: number; right: number; y: number }[] = [];
  return labels.map((label) => {
    const width = Math.min(label.width, Math.max(0, chartWidth - 8));
    const x = Math.max(width / 2 + 4, Math.min(label.x, chartWidth - width / 2 - 4));
    const interval = { left: x - width / 2 - 6, right: x + width / 2 + 6 };
    let lane = 0;
    const baseY = label.y ?? 0;
    while (occupied.some((other) => interval.right > other.left && interval.left < other.right && Math.abs(baseY - lane * 20 - other.y) < 20)) {
      lane += 1;
    }
    occupied.push({ ...interval, y: baseY - lane * 20 });
    return { x, lane };
  });
}
