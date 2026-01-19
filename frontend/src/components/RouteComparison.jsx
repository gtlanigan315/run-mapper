function RouteComparison({ target, route, color }) {
  if (!target || !route) return null;

  const comparisons = [
    {
      label: 'Distance',
      unit: 'km',
      target: target.distance,
      actual: route.distance_km,
      format: (v) => v.toFixed(1),
    },
    {
      label: 'Elevation Gain',
      unit: 'm',
      target: target.elevation,
      actual: route.elevation_gain_m,
      format: (v) => Math.round(v),
    },
    {
      label: 'Avg Grade',
      unit: '%',
      target: target.grade,
      actual: (route.elevation_gain_m / (route.distance_km * 1000)) * 100,
      format: (v) => v.toFixed(1),
    },
  ];

  return (
    <div className="route-comparison">
      {comparisons.map((comp) => {
        const diff = comp.actual - comp.target;
        const diffPercent = comp.target > 0 ? (diff / comp.target) * 100 : 0;
        const isClose = Math.abs(diffPercent) < 10;
        const isOver = diff > 0;

        return (
          <div key={comp.label} className="comparison-item">
            <div className="comparison-header">
              <span className="comparison-label">{comp.label}</span>
              <span className={`comparison-diff ${isClose ? 'close' : isOver ? 'over' : 'under'}`}>
                {diff >= 0 ? '+' : ''}{comp.format(diff)} {comp.unit}
              </span>
            </div>
            <div className="comparison-bars">
              <div className="bar-row">
                <span className="bar-label">Target</span>
                <div className="bar-track">
                  <div
                    className="bar-fill target"
                    style={{
                      width: `${Math.min((comp.target / Math.max(comp.target, comp.actual)) * 100, 100)}%`,
                    }}
                  />
                </div>
                <span className="bar-value">{comp.format(comp.target)}</span>
              </div>
              <div className="bar-row">
                <span className="bar-label">Route</span>
                <div className="bar-track">
                  <div
                    className="bar-fill actual"
                    style={{
                      width: `${Math.min((comp.actual / Math.max(comp.target, comp.actual)) * 100, 100)}%`,
                      backgroundColor: color,
                    }}
                  />
                </div>
                <span className="bar-value">{comp.format(comp.actual)}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default RouteComparison;
