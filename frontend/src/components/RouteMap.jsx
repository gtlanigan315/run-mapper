import { useEffect } from 'react';
import { MapContainer, TileLayer, Polyline, useMap, ZoomControl } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { ROUTE_COLORS } from '../constants/colors';

function MapUpdater({ routes, selectedRoute }) {
  const map = useMap();

  useEffect(() => {
    if (routes.length > 0) {
      const routeToFocus = selectedRoute !== null ? routes[selectedRoute] : routes[0];
      if (routeToFocus?.coordinates?.length > 0) {
        const bounds = routeToFocus.coordinates.map(([lat, lon]) => [lat, lon]);
        map.fitBounds(bounds, { padding: [50, 50] });
      }
    }
  }, [routes, selectedRoute, map]);

  return null;
}

function RouteMap({ routes, selectedRoute, onRouteSelect }) {
  const defaultCenter = [40.7831, -73.9712]; // Manhattan
  const defaultZoom = 13;

  return (
    <div className="route-map">
      <MapContainer
        center={defaultCenter}
        zoom={defaultZoom}
        style={{ height: '100%', width: '100%' }}
        zoomControl={false}
      >
        {/* CartoDB Positron - clean, minimal light style */}
        <TileLayer
          attribution='&copy; <a href="https://carto.com/attributions">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          subdomains="abcd"
        />
        <ZoomControl position="bottomright" />

        {/* Render non-selected routes first (below) */}
        {routes.map((route, index) =>
          selectedRoute !== index && (
            <Polyline
              key={`bg-${index}`}
              positions={route.coordinates.map(([lat, lon]) => [lat, lon])}
              color={ROUTE_COLORS[index % ROUTE_COLORS.length]}
              weight={4}
              opacity={selectedRoute === null ? 0.7 : 0.25}
              lineCap="round"
              lineJoin="round"
              eventHandlers={{
                click: () => onRouteSelect?.(index),
              }}
            />
          )
        )}

        {/* Render selected route last (on top) */}
        {selectedRoute !== null && routes[selectedRoute] && (
          <>
            {/* Shadow/glow effect */}
            <Polyline
              positions={routes[selectedRoute].coordinates.map(([lat, lon]) => [lat, lon])}
              color={ROUTE_COLORS[selectedRoute % ROUTE_COLORS.length]}
              weight={10}
              opacity={0.2}
              lineCap="round"
              lineJoin="round"
            />
            {/* Main line */}
            <Polyline
              positions={routes[selectedRoute].coordinates.map(([lat, lon]) => [lat, lon])}
              color={ROUTE_COLORS[selectedRoute % ROUTE_COLORS.length]}
              weight={5}
              opacity={1}
              lineCap="round"
              lineJoin="round"
              eventHandlers={{
                click: () => onRouteSelect?.(selectedRoute),
              }}
            />
          </>
        )}

        <MapUpdater routes={routes} selectedRoute={selectedRoute} />
      </MapContainer>
    </div>
  );
}

export default RouteMap;
