function ProfileSummary({ profile }) {
  if (!profile) {
    return null;
  }

  return (
    <div className="profile-summary">
      <h3>GPX Profile Summary</h3>
      <div className="stats-grid">
        <div className="stat-box">
          <span className="stat-value">{profile.distance_km.toFixed(2)}</span>
          <span className="stat-label">Distance (km)</span>
        </div>
        <div className="stat-box">
          <span className="stat-value">+{profile.elevation_gain_m.toFixed(0)}</span>
          <span className="stat-label">Elevation Gain (m)</span>
        </div>
        <div className="stat-box">
          <span className="stat-value">-{profile.elevation_loss_m.toFixed(0)}</span>
          <span className="stat-label">Elevation Loss (m)</span>
        </div>
        <div className="stat-box">
          <span className="stat-value">{profile.min_elevation_m.toFixed(0)} - {profile.max_elevation_m.toFixed(0)}</span>
          <span className="stat-label">Elevation Range (m)</span>
        </div>
        {profile.steepest_climb_grade > 0 && (
          <>
            <div className="stat-box">
              <span className="stat-value">{profile.steepest_climb_grade.toFixed(1)}%</span>
              <span className="stat-label">Steepest Grade</span>
            </div>
            <div className="stat-box">
              <span className="stat-value">{profile.steepest_climb_distance_m.toFixed(0)}m</span>
              <span className="stat-label">Climb Distance</span>
            </div>
            <div className="stat-box">
              <span className="stat-value">+{profile.steepest_climb_gain_m.toFixed(0)}m</span>
              <span className="stat-label">Climb Gain</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default ProfileSummary;
