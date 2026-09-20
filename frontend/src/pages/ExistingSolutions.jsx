const solutions = [
  {
    name: "India-WRIS",
    category: "Water Resources Data",
    description:
      "Provides water-resources information, datasets, maps, and related information for India.",
    relevance:
      "Useful as a reference source for water-resource and hydrological datasets.",
  },
  {
    name: "IMD",
    category: "Weather Data",
    description:
      "Provides meteorological observations, forecasts, rainfall information, and weather-related services.",
    relevance:
      "Useful for rainfall and weather inputs required for flood monitoring and forecasting.",
  },
  {
    name: "CWC",
    category: "Flood Monitoring",
    description:
      "Provides river monitoring, hydrological information, and flood-related information for monitored river systems.",
    relevance:
      "Useful for river-level and hydrological information.",
  },
  {
    name: "ISRO / Bhuvan",
    category: "GIS & Earth Observation",
    description:
      "Provides geospatial and Earth-observation resources that can support mapping and geographic analysis.",
    relevance:
      "Useful for geographic visualization and spatial analysis.",
  },
];

function ExistingSolutions() {
  return (
    <div className="existing-solutions-page">
      <div className="page-heading">
        <div>
          <h1>Existing Solutions</h1>
          <p>
            Reference systems and data sources relevant to flood intelligence.
          </p>
        </div>
      </div>

      <div className="solutions-grid">
        {solutions.map((solution) => (
          <div className="solution-card" key={solution.name}>
            <div className="solution-card-header">
              <div>
                <h2>{solution.name}</h2>
                <span className="solution-category">
                  {solution.category}
                </span>
              </div>
            </div>

            <p className="solution-description">
              {solution.description}
            </p>

            <div className="solution-relevance">
              <strong>Q-FLARE Relevance</strong>
              <p>{solution.relevance}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default ExistingSolutions;