import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

function ElevationChart({ profile, title, color = '#6366f1' }) {
  if (!profile || profile.length === 0) {
    return null;
  }

  const data = profile.map(([distance, elevation]) => ({
    distance: parseFloat(distance.toFixed(2)),
    elevation: Math.round(elevation),
  }));

  const elevations = data.map((d) => d.elevation);
  const minElevation = Math.min(...elevations);
  const maxElevation = Math.max(...elevations);
  const range = maxElevation - minElevation;
  const padding = Math.max(range * 0.1, 5);

  // Round domain to nice values
  const yMin = Math.floor((minElevation - padding) / 10) * 10;
  const yMax = Math.ceil((maxElevation + padding) / 10) * 10;

  return (
    <div className="elevation-chart">
      {title && <h4>{title}</h4>}
      <ResponsiveContainer width="100%" height={150}>
        <AreaChart data={data} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
          <defs>
            <linearGradient id={`gradient-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.4} />
              <stop offset="100%" stopColor={color} stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="distance"
            tickFormatter={(val) => `${val}`}
            tick={{ fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={[yMin, yMax]}
            tickFormatter={(val) => `${val}m`}
            tick={{ fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={45}
          />
          <Tooltip
            formatter={(value) => [`${value} m`, 'Elevation']}
            labelFormatter={(value) => `${value} km`}
          />
          <Area
            type="monotone"
            dataKey="elevation"
            stroke={color}
            strokeWidth={2}
            fill={`url(#gradient-${color.replace('#', '')})`}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export default ElevationChart;
