const ROUTE_COLORS = [
  '#2196F3', '#4CAF50', '#FF9800', '#9C27B0',
  '#F44336', '#00BCD4', '#FFEB3B', '#795548',
];

function RouteList({ routes, selectedRoute, onRouteSelect }) {
  if (routes.length === 0) {
    return null;
  }

  return (
    <div className="route-list">
      <h3>Found Routes</h3>
      <div className="routes">
        {routes.map((route, index) => (
          <div
            key={index}
            className={`route-card ${selectedRoute === index ? 'selected' : ''}`}
            onClick={() => onRouteSelect(index)}
            style={{ borderLeftColor: ROUTE_COLORS[index % ROUTE_COLORS.length] }}
          >
            <div className="route-header">
              <span
                className="route-color"
                style={{ backgroundColor: ROUTE_COLORS[index % ROUTE_COLORS.length] }}
              />
              <span className="route-name">{route.name}</span>
              <span className="similarity-score">
                {(route.similarity_score * 100).toFixed(0)}% match
              </span>
            </div>
            <div className="route-stats">
              <div className="stat">
                <span className="stat-value">{route.distance_km.toFixed(2)}</span>
                <span className="stat-label">km</span>
              </div>
              <div className="stat">
                <span className="stat-value">+{route.elevation_gain_m.toFixed(0)}</span>
                <span className="stat-label">m gain</span>
              </div>
              <div className="stat">
                <span className="stat-value">-{route.elevation_loss_m.toFixed(0)}</span>
                <span className="stat-label">m loss</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default RouteList;
