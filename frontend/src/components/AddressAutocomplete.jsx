import { useState, useEffect, useRef } from 'react';

// Photon API with US location bias (centered on Kansas for continental US coverage)
const PHOTON_API = 'https://photon.komoot.io/api/';
const US_CENTER = { lat: 39.8283, lon: -98.5795 };

function AddressAutocomplete({ value, onChange, placeholder, disabled }) {
  const [query, setQuery] = useState(value || '');
  const [suggestions, setSuggestions] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const wrapperRef = useRef(null);
  const debounceRef = useRef(null);

  // Sync external value changes
  useEffect(() => {
    setQuery(value || '');
  }, [value]);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const fetchSuggestions = async (searchQuery) => {
    if (searchQuery.length < 2) {
      setSuggestions([]);
      return;
    }

    setLoading(true);
    try {
      // Build URL with US location bias
      const params = new URLSearchParams({
        q: searchQuery,
        limit: 7,
        lat: US_CENTER.lat,
        lon: US_CENTER.lon,
        lang: 'en',
      });

      const response = await fetch(`${PHOTON_API}?${params}`);
      const data = await response.json();

      // Process and prioritize US results
      const results = data.features
        .map((feature) => {
          const props = feature.properties;
          const isUS = props.country === 'United States' ||
                       props.country === 'United States of America' ||
                       props.countrycode === 'US';

          // Build display string
          const parts = [];
          if (props.name && props.name !== props.city) parts.push(props.name);
          if (props.housenumber && props.street) {
            parts.push(`${props.housenumber} ${props.street}`);
          } else if (props.street) {
            parts.push(props.street);
          }
          if (props.city) parts.push(props.city);
          if (props.state) parts.push(props.state);

          // Only add country if not US (keep US results cleaner)
          if (!isUS && props.country) {
            parts.push(props.country);
          }

          return {
            id: feature.properties.osm_id || Math.random(),
            display: parts.join(', ') || props.name || 'Unknown location',
            city: props.city || props.name,
            state: props.state,
            country: props.country,
            countryCode: props.countrycode,
            coordinates: feature.geometry.coordinates,
            isUS,
            type: props.osm_value || props.type,
          };
        })
        // Sort US results to the top
        .sort((a, b) => {
          if (a.isUS && !b.isUS) return -1;
          if (!a.isUS && b.isUS) return 1;
          return 0;
        })
        // Limit to 5 results
        .slice(0, 5);

      setSuggestions(results);
      setIsOpen(results.length > 0);
    } catch (error) {
      console.error('Autocomplete error:', error);
      setSuggestions([]);
    } finally {
      setLoading(false);
    }
  };

  const handleInputChange = (e) => {
    const newValue = e.target.value;
    setQuery(newValue);
    setSelectedIndex(-1);

    // Debounce API calls
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    debounceRef.current = setTimeout(() => {
      fetchSuggestions(newValue);
    }, 250);
  };

  const handleSelect = (suggestion) => {
    setQuery(suggestion.display);
    onChange(suggestion.display);
    setIsOpen(false);
    setSuggestions([]);
  };

  const handleKeyDown = (e) => {
    if (!isOpen || suggestions.length === 0) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex((prev) =>
          prev < suggestions.length - 1 ? prev + 1 : prev
        );
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex((prev) => (prev > 0 ? prev - 1 : -1));
        break;
      case 'Enter':
        e.preventDefault();
        if (selectedIndex >= 0) {
          handleSelect(suggestions[selectedIndex]);
        }
        break;
      case 'Escape':
        setIsOpen(false);
        break;
    }
  };

  const handleFocus = () => {
    if (suggestions.length > 0) {
      setIsOpen(true);
    }
  };

  // Get icon based on place type
  const getIcon = (suggestion) => {
    if (suggestion.type === 'city' || suggestion.type === 'town') return '🏙️';
    if (suggestion.type === 'village' || suggestion.type === 'suburb') return '🏘️';
    if (suggestion.type === 'house' || suggestion.type === 'building') return '🏠';
    return '📍';
  };

  return (
    <div className="autocomplete-wrapper" ref={wrapperRef}>
      <input
        type="text"
        value={query}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        onFocus={handleFocus}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
      />

      {loading && <span className="autocomplete-loading" />}

      {isOpen && suggestions.length > 0 && (
        <ul className="autocomplete-dropdown">
          {suggestions.map((suggestion, index) => (
            <li
              key={suggestion.id}
              className={`autocomplete-item ${index === selectedIndex ? 'selected' : ''}`}
              onClick={() => handleSelect(suggestion)}
              onMouseEnter={() => setSelectedIndex(index)}
            >
              <span className="autocomplete-icon">{getIcon(suggestion)}</span>
              <span className="autocomplete-text">
                {suggestion.display}
                {!suggestion.isUS && suggestion.country && (
                  <span style={{ opacity: 0.5, marginLeft: '4px' }}>
                    ({suggestion.countryCode || suggestion.country})
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default AddressAutocomplete;
