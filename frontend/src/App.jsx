import { useState, useEffect, useRef } from 'react';
import RouteMap from './components/RouteMap';
import ElevationChart from './components/ElevationChart';
import RouteComparison from './components/RouteComparison';
import AddressAutocomplete from './components/AddressAutocomplete';
import {
  analyzeGpx,
  findRoutes,
  getStravaAuthUrl,
  exchangeStravaToken,
  saveStravaTokens,
  getStravaTokens,
  clearStravaTokens,
  getValidStravaToken,
} from './services/api';
import { ROUTE_COLORS } from './constants/colors';
import './App.css';

const RUNNING_QUOTES = [
  { text: "The miracle isn't that I finished. The miracle is that I had the courage to start.", author: "John Bingham" },
  { text: "Run when you can, walk if you have to, crawl if you must; just never give up.", author: "Dean Karnazes" },
  { text: "Running is the greatest metaphor for life, because you get out of it what you put into it.", author: "Oprah Winfrey" },
  { text: "The real purpose of running isn't to win a race. It's to test the limits of the human heart.", author: "Bill Bowerman" },
  { text: "Every mile is a gift. Remember that.", author: "Shalane Flanagan" },
  { text: "Running allows me to set my mind free.", author: "Kara Goucher" },
  { text: "The body achieves what the mind believes.", author: "Unknown" },
  { text: "I run because long after my footprints fade, the training will live on in my heart.", author: "Unknown" },
  { text: "If you want to become the best runner you can be, start now.", author: "Hal Higdon" },
  { text: "Good things come slow, especially in distance running.", author: "Bill Dellinger" },
  { text: "Hills are speedwork in disguise.", author: "Frank Shorter" },
  { text: "There is magic in misery. Just ask any runner.", author: "Dean Karnazes" },
  { text: "Running is nothing more than a series of arguments between the part of your brain that wants to stop and the part that wants to keep going.", author: "Unknown" },
  { text: "A runner must run with dreams in his heart.", author: "Emil Zatopek" },
  { text: "The obsession with running is really an obsession with the potential for more and more life.", author: "George Sheehan" },
  { text: "I always loved running. It was something you could do by yourself and under your own power.", author: "Jesse Owens" },
  { text: "We are what we repeatedly do. Excellence, then, is not an act, but a habit.", author: "Aristotle" },
  { text: "The human body is capable of amazing physical deeds. If we could just free ourselves from our perceived limitations.", author: "Dean Karnazes" },
  { text: "Running is alone time that lets my brain unspool the tangles that build up over days.", author: "Rob Haneisen" },
  { text: "I don't run to add days to my life, I run to add life to my days.", author: "Ronald Rook" },
  { text: "Your body will argue that there is no justifiable reason to continue. Your only recourse is to call on your spirit.", author: "Dick Collins" },
  { text: "Strength does not come from physical capacity. It comes from an indomitable will.", author: "Mahatma Gandhi" },
  { text: "The will to win means nothing without the will to prepare.", author: "Juma Ikangaa" },
  { text: "Running is my meditation, mind flush, cosmic telephone, mood elevator and spiritual communion.", author: "Lorraine Moller" },
  { text: "Life is short. Running makes it seem longer.", author: "Baron Hansen" },
  { text: "Remember, the feeling you get from a good run is far better than the feeling you get from sitting around wishing you were running.", author: "Sarah Condor" },
  { text: "In running, it doesn't matter whether you come in first, in the middle of the pack, or last. You can say, 'I have finished.'", author: "Fred Lebow" },
  { text: "Most people run a race to see who is fastest. I run a race to see who has the most guts.", author: "Steve Prefontaine" },
  { text: "To give anything less than your best is to sacrifice the gift.", author: "Steve Prefontaine" },
  { text: "Someone who is busier than you is running right now.", author: "Nike" },
  { text: "A mile in the morning is worth two in the afternoon.", author: "Unknown" },
  { text: "Running is real and relatively simple. But it ain't easy.", author: "Mark Will-Weber" },
  { text: "Ask yourself: Can I give more? The answer is usually yes.", author: "Paul Tergat" },
  { text: "If you run, you are a runner. It doesn't matter how fast or how far.", author: "John Bingham" },
  { text: "It's very hard in the beginning to understand that the whole idea is not to beat the other runners. Eventually you learn that the competition is against the little voice inside you that wants you to quit.", author: "George Sheehan" },
  { text: "There's not one body type that equates to success. Accept the body you have and be the best you can be with it.", author: "Mary Cullen" },
  { text: "Act like a horse. Be dumb. Just run.", author: "Jumbo Elliott" },
  { text: "Fast running isn't forced. You have to relax and let the run come out of you.", author: "Desiree Linden" },
  { text: "That's the thing about running: your greatest runs are rarely measured by racing success.", author: "Kara Goucher" },
  { text: "Don't dream of winning, train for it!", author: "Mo Farah" },
  { text: "I breathe in strength and breathe out weakness.", author: "Amy Hastings Cragg" },
  { text: "You have to wonder at times what you're doing out there. But I'm addicted to running.", author: "Ryan Hall" },
  { text: "The reason we race isn't so much to beat each other, but to be with each other.", author: "Christopher McDougall" },
  { text: "I run so my goals in life will continue to get bigger instead of my belly.", author: "Bill Kirby" },
  { text: "Whether you think you can or you think you can't, you're right.", author: "Henry Ford" },
  { text: "Runners just do it. They run for the finish line even if someone else has crosed it first.", author: "Unknown" },
  { text: "There are clubs you can't belong to, neighborhoods you can't live in, schools you can't get into, but the roads are always open.", author: "Nike" },
  { text: "What seems hard now will one day be your warm-up.", author: "Unknown" },
  { text: "No human is limited.", author: "Eliud Kipchoge" },
  { text: "Run often. Run long. But never outrun your joy of running.", author: "Julie Isphording" },
];

function App() {
  // Input mode: 'gpx' or 'manual'
  const [inputMode, setInputMode] = useState('gpx');

  // Form state
  const [location, setLocation] = useState('');
  const [gpxFile, setGpxFile] = useState(null);
  const [gpxProfile, setGpxProfile] = useState(null);

  // Strava state
  const [stravaConnected, setStravaConnected] = useState(false);
  const [stravaLoading, setStravaLoading] = useState(false);
  const [manualDistance, setManualDistance] = useState(5);
  const [manualElevationGain, setManualElevationGain] = useState(50);
  const [manualGrade, setManualGrade] = useState('');

  // Results state
  const [routes, setRoutes] = useState([]);
  const [selectedRoute, setSelectedRoute] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [quoteIndex, setQuoteIndex] = useState(0);

  // Cycle through quotes while loading
  useEffect(() => {
    if (!loading) return;

    // Start with a random quote
    setQuoteIndex(Math.floor(Math.random() * RUNNING_QUOTES.length));

    const interval = setInterval(() => {
      setQuoteIndex((prev) => (prev + 1) % RUNNING_QUOTES.length);
    }, 8000);

    return () => clearInterval(interval);
  }, [loading]);

  // Check for existing Strava tokens on mount
  useEffect(() => {
    const tokens = getStravaTokens();
    if (tokens) {
      setStravaConnected(true);
    }
  }, []);

  // Handle Strava OAuth callback (use ref to prevent double execution in StrictMode)
  const stravaCallbackHandled = useRef(false);
  useEffect(() => {
    const handleStravaCallback = async () => {
      if (stravaCallbackHandled.current) return;

      const urlParams = new URLSearchParams(window.location.search);
      const code = urlParams.get('code');
      const error = urlParams.get('error');

      if (error) {
        console.error('Strava OAuth error:', error);
        // Clear the URL params
        window.history.replaceState({}, document.title, window.location.pathname);
        return;
      }

      if (code) {
        stravaCallbackHandled.current = true;
        setStravaLoading(true);
        try {
          const tokens = await exchangeStravaToken(code);
          saveStravaTokens(tokens);
          setStravaConnected(true);
        } catch (err) {
          console.error('Failed to exchange Strava token:', err);
          setError('Failed to connect to Strava');
          stravaCallbackHandled.current = false; // Allow retry on error
        } finally {
          setStravaLoading(false);
          // Clear the URL params
          window.history.replaceState({}, document.title, window.location.pathname);
        }
      }
    };

    handleStravaCallback();
  }, []);

  const handleStravaConnect = async () => {
    try {
      setStravaLoading(true);
      const authUrl = await getStravaAuthUrl();
      window.location.href = authUrl;
    } catch (err) {
      console.error('Failed to get Strava auth URL:', err);
      setError('Failed to connect to Strava. Make sure the backend is configured with Strava credentials.');
      setStravaLoading(false);
    }
  };

  const handleStravaDisconnect = () => {
    clearStravaTokens();
    setStravaConnected(false);
  };

  const handleGpxChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.gpx')) {
      setError('Please select a GPX file');
      return;
    }

    setGpxFile(file);
    setError(null);

    try {
      const profile = await analyzeGpx(file);
      setGpxProfile(profile);
      // Auto-fill manual fields from GPX
      setManualDistance(profile.distance_km);
      setManualElevationGain(profile.elevation_gain_m);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to analyze GPX file');
      setGpxFile(null);
      setGpxProfile(null);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!location.trim()) {
      setError('Please enter your location');
      return;
    }

    let distance, elevationGain, elevationLoss, profile;

    if (inputMode === 'gpx') {
      if (!gpxProfile) {
        setError('Please upload a GPX file first');
        return;
      }
      distance = gpxProfile.distance_km;
      elevationGain = gpxProfile.elevation_gain_m;
      elevationLoss = gpxProfile.elevation_loss_m;
      profile = gpxProfile.profile;
    } else {
      distance = manualDistance;
      elevationLoss = 0;
      profile = null;
      // If grade is provided, calculate elevation gain from grade and distance
      if (manualGrade && !isNaN(parseFloat(manualGrade))) {
        elevationGain = (parseFloat(manualGrade) / 100) * (distance * 1000);
      } else {
        elevationGain = manualElevationGain;
      }
    }

    setLoading(true);
    setError(null);
    setRoutes([]);
    setSelectedRoute(null);

    try {
      console.log('Searching for routes...', { location, distance, elevationGain, elevationLoss, stravaConnected });

      // Get Strava token if connected
      let stravaToken = null;
      if (stravaConnected) {
        stravaToken = await getValidStravaToken();
      }

      const response = await findRoutes(location, distance, elevationGain, 5, stravaToken, elevationLoss, profile);
      console.log('Routes found:', response);

      if (!response.routes || response.routes.length === 0) {
        setError('No routes found in this area. Try a different location or distance.');
        return;
      }

      // Add AI summaries to routes
      const routesWithSummaries = response.routes.map((route, index) => {
        try {
          return {
            ...route,
            aiSummary: generateRouteSummary(route, distance, elevationGain, gpxProfile),
          };
        } catch (summaryErr) {
          console.error('Error generating summary for route', index, summaryErr);
          return {
            ...route,
            aiSummary: {
              gradeDesc: 'unknown',
              avgGrade: '0',
              pros: [],
              cons: [],
              recommendation: 'Route data available',
            },
          };
        }
      });

      setRoutes(routesWithSummaries);
      if (routesWithSummaries.length > 0) {
        setSelectedRoute(0);
      }
    } catch (err) {
      console.error('Error finding routes:', err);
      setError(err.response?.data?.detail || err.message || 'Failed to find routes. Try a different location.');
    } finally {
      setLoading(false);
    }
  };

  // Generate AI-like summary for a route
  const generateRouteSummary = (route, targetDistance, targetElevation, gpxProfile) => {
    const distanceDiff = Math.abs(route.distance_km - targetDistance);
    const distanceMatch = distanceDiff < 0.5 ? 'excellent' : distanceDiff < 1 ? 'good' : 'moderate';

    const elevDiff = Math.abs(route.elevation_gain_m - targetElevation);
    const elevMatch = elevDiff < 20 ? 'excellent' : elevDiff < 50 ? 'good' : 'moderate';

    const avgGrade = (route.elevation_gain_m / (route.distance_km * 1000)) * 100;
    const gradeDesc = avgGrade < 2 ? 'flat' : avgGrade < 5 ? 'rolling' : avgGrade < 8 ? 'hilly' : 'challenging';

    const pros = [];
    const cons = [];

    if (distanceMatch === 'excellent') pros.push('Distance matches perfectly');
    else if (distanceMatch === 'good') pros.push('Distance is close to target');
    else cons.push(`Distance is ${route.distance_km > targetDistance ? 'longer' : 'shorter'} than target`);

    if (elevMatch === 'excellent') pros.push('Elevation gain matches well');
    else if (elevMatch === 'good') pros.push('Similar elevation profile');
    else cons.push(`${route.elevation_gain_m > targetElevation ? 'More' : 'Less'} elevation than target`);

    if (route.similarity_score >= 0.8) pros.push('Great overall match for training');

    const recommendation = route.similarity_score >= 0.75
      ? 'Highly recommended for your training goals'
      : route.similarity_score >= 0.5
        ? 'Good alternative with some differences'
        : 'Consider if other options unavailable';

    return {
      gradeDesc,
      avgGrade: avgGrade.toFixed(1),
      pros,
      cons,
      recommendation,
    };
  };

  const handleRouteSelect = (index) => {
    setSelectedRoute(index === selectedRoute ? null : index);
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Run Mapper</h1>
        <div className="header-actions">
          {stravaConnected ? (
            <button
              className="strava-btn connected"
              onClick={handleStravaDisconnect}
              disabled={stravaLoading}
            >
              <span className="strava-icon">S</span>
              Strava Connected
            </button>
          ) : (
            <button
              className="strava-btn"
              onClick={handleStravaConnect}
              disabled={stravaLoading}
            >
              <span className="strava-icon">S</span>
              {stravaLoading ? 'Connecting...' : 'Connect Strava'}
            </button>
          )}
        </div>
      </header>

      <main className="app-main">
        <aside className="sidebar">
          <form onSubmit={handleSubmit} className="search-form">
            {/* Location Input */}
            <div className="form-section">
              <h3>Your Location</h3>
              <div className="form-group">
                <AddressAutocomplete
                  value={location}
                  onChange={setLocation}
                  placeholder="Start typing your address or city..."
                  disabled={loading}
                />
              </div>
            </div>

            {/* Input Mode Toggle */}
            <div className="form-section">
              <h3>Route Criteria</h3>
              <div className="input-mode-toggle">
                <button
                  type="button"
                  className={`mode-btn ${inputMode === 'gpx' ? 'active' : ''}`}
                  onClick={() => setInputMode('gpx')}
                >
                  Upload GPX
                </button>
                <button
                  type="button"
                  className={`mode-btn ${inputMode === 'manual' ? 'active' : ''}`}
                  onClick={() => setInputMode('manual')}
                >
                  Enter Manually
                </button>
              </div>
            </div>

            {/* GPX Upload */}
            {inputMode === 'gpx' && (
              <div className="form-section">
                <label className="file-input-label">
                  <input
                    type="file"
                    accept=".gpx"
                    onChange={handleGpxChange}
                    disabled={loading}
                  />
                  <span className="file-input-button">
                    {gpxFile ? gpxFile.name : 'Choose GPX File'}
                  </span>
                </label>

                {gpxProfile && (
                  <div className="gpx-summary">
                    <div className="gpx-stat">
                      <span className="value">{gpxProfile.distance_km.toFixed(1)}</span>
                      <span className="label">km</span>
                    </div>
                    <div className="gpx-stat">
                      <span className="value">+{gpxProfile.elevation_gain_m.toFixed(0)}</span>
                      <span className="label">m gain</span>
                    </div>
                    <div className="gpx-stat">
                      <span className="value">{((gpxProfile.elevation_gain_m / (gpxProfile.distance_km * 1000)) * 100).toFixed(1)}%</span>
                      <span className="label">avg grade</span>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Manual Input */}
            {inputMode === 'manual' && (
              <div className="form-section manual-inputs">
                <div className="form-group">
                  <label>Distance (km)</label>
                  <input
                    type="number"
                    value={manualDistance}
                    onChange={(e) => setManualDistance(parseFloat(e.target.value) || 0)}
                    min="0.5"
                    max="100"
                    step="0.5"
                    disabled={loading}
                  />
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Elevation Gain (m)</label>
                    <input
                      type="number"
                      value={manualElevationGain}
                      onChange={(e) => {
                        setManualElevationGain(parseFloat(e.target.value) || 0);
                        setManualGrade('');
                      }}
                      min="0"
                      max="5000"
                      step="10"
                      disabled={loading}
                    />
                  </div>

                  <div className="form-group">
                    <label>Or Avg Grade (%)</label>
                    <input
                      type="number"
                      value={manualGrade}
                      onChange={(e) => setManualGrade(e.target.value)}
                      placeholder="e.g., 3"
                      min="0"
                      max="30"
                      step="0.5"
                      disabled={loading}
                    />
                  </div>
                </div>
              </div>
            )}

            {error && <p className="error">{error}</p>}

            <button type="submit" className="submit-btn" disabled={loading}>
              {loading ? 'Finding Routes...' : 'Find Matching Routes'}
            </button>
          </form>

          {/* Loading State */}
          {loading && (
            <div className="loading-section">
              <div className="loading-spinner" />
              <p className="loading-text">Finding routes near you...</p>
              <blockquote className="loading-quote" key={quoteIndex}>
                <p>"{RUNNING_QUOTES[quoteIndex].text}"</p>
                <cite>— {RUNNING_QUOTES[quoteIndex].author}</cite>
              </blockquote>
            </div>
          )}

          {/* Results */}
          {!loading && routes.length > 0 && (
            <div className="results-section">
              <h3>Matching Routes</h3>
              <div className="routes-list">
                {routes.map((route, index) => {
                  const routeColor = ROUTE_COLORS[index % ROUTE_COLORS.length];
                  const isSelected = selectedRoute === index;
                  return (
                  <div
                    key={index}
                    className={`route-card ${isSelected ? 'selected' : ''}`}
                    onClick={() => handleRouteSelect(index)}
                    style={{
                      borderLeftColor: routeColor,
                      ...(isSelected && {
                        backgroundColor: `${routeColor}20`,
                        borderColor: `${routeColor}66`,
                      }),
                    }}
                  >
                    <div className="route-header">
                      <span
                        className="route-color"
                        style={{ backgroundColor: routeColor }}
                      />
                      <span className="route-name">{route.name}</span>
                      {(route.source === 'strava' || route.source === 'strava-weighted') && (
                        <span className="strava-badge">
                          {route.source === 'strava' ? 'Strava' : 'Popular'}
                        </span>
                      )}
                      <span className="match-score">
                        {(route.similarity_score * 100).toFixed(0)}% match
                      </span>
                    </div>

                    <div className="route-stats">
                      <span>{route.distance_km.toFixed(1)} km</span>
                      <span>+{route.elevation_gain_m.toFixed(0)}m</span>
                      <span>{route.aiSummary.gradeDesc}</span>
                    </div>

                    <div className="route-summary">
                      <p className="recommendation">{route.aiSummary.recommendation}</p>
                      {route.aiSummary.pros.length > 0 && (
                        <ul className="pros">
                          {route.aiSummary.pros.map((pro, i) => (
                            <li key={i}>✓ {pro}</li>
                          ))}
                        </ul>
                      )}
                      {route.aiSummary.cons.length > 0 && (
                        <ul className="cons">
                          {route.aiSummary.cons.map((con, i) => (
                            <li key={i}>• {con}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                  );
                })}
              </div>
            </div>
          )}
        </aside>

        <section className="content">
          <div className="map-container">
            <RouteMap
              routes={routes}
              selectedRoute={selectedRoute}
              onRouteSelect={handleRouteSelect}
            />
          </div>

          {(gpxProfile || (selectedRoute !== null && routes[selectedRoute])) && (
            <div className="charts-container">
              {/* Comparison bars when a route is selected */}
              {selectedRoute !== null && routes[selectedRoute] && (
                <RouteComparison
                  target={{
                    distance: inputMode === 'gpx' && gpxProfile ? gpxProfile.distance_km : manualDistance,
                    elevation: inputMode === 'gpx' && gpxProfile ? gpxProfile.elevation_gain_m : manualElevationGain,
                    grade: inputMode === 'gpx' && gpxProfile
                      ? (gpxProfile.elevation_gain_m / (gpxProfile.distance_km * 1000)) * 100
                      : manualGrade ? parseFloat(manualGrade) : (manualElevationGain / (manualDistance * 1000)) * 100,
                  }}
                  route={routes[selectedRoute]}
                  color={ROUTE_COLORS[selectedRoute % ROUTE_COLORS.length]}
                />
              )}

              {gpxProfile && inputMode === 'gpx' && (
                <ElevationChart
                  profile={gpxProfile.profile}
                  title="Target Profile (GPX)"
                  color="#E91E63"
                />
              )}

              {selectedRoute !== null && routes[selectedRoute] && (
                <ElevationChart
                  profile={routes[selectedRoute].profile}
                  title={`${routes[selectedRoute].name} - ${routes[selectedRoute].aiSummary.avgGrade}% avg grade`}
                  color={ROUTE_COLORS[selectedRoute % ROUTE_COLORS.length]}
                />
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;
