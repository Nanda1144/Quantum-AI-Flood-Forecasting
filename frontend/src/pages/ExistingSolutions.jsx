import React from "react";

function ExistingSolutions() {
  const existingSolutions = [
    {
      name: "Traditional Flood Monitoring",
      technology: "Rain gauges, river gauges, manual monitoring",
      purpose: "Monitor rainfall and water levels",
      limitation:
        "Monitoring is often location-specific and may not provide integrated prediction and response planning.",
    },
    {
      name: "Weather Forecasting Systems",
      technology: "Weather stations and numerical weather models",
      purpose: "Predict rainfall and weather conditions",
      limitation:
        "Weather information alone does not provide complete flood-risk, resource, or disaster-response optimization.",
    },
    {
      name: "Satellite-Based Flood Monitoring",
      technology: "Satellite imagery and remote sensing",
      purpose: "Detect and monitor flooded areas",
      limitation:
        "Satellite observations can be affected by revisit time, cloud cover, processing requirements, and limited real-time response capability.",
    },
    {
      name: "GIS-Based Flood Mapping",
      technology: "GIS, elevation data, spatial analysis",
      purpose: "Visualize flood-prone areas and affected regions",
      limitation:
        "GIS provides strong spatial analysis but generally requires integration with forecasting and decision-support systems.",
    },
  ];

  const technologyComparison = [
    {
      feature: "Dataset Management",
      existing: "Separate datasets and manual processing",
      qflare: "Centralized upload, validation, quality analysis and preprocessing",
    },
    {
      feature: "Flood Forecasting",
      existing: "Forecasting systems operate independently",
      qflare: "Integrated with the overall flood intelligence pipeline",
    },
    {
      feature: "GIS Analysis",
      existing: "Separate mapping and spatial-analysis tools",
      qflare: "Integrated with flood-risk and decision workflows",
    },
    {
      feature: "Risk Analysis",
      existing: "Often requires separate analysis",
      qflare: "Designed to combine multiple data sources for risk assessment",
    },
    {
      feature: "Optimization",
      existing: "Limited or classical optimization",
      qflare: "Quantum-inspired / QUBO-QAOA optimization component",
    },
    {
      feature: "Disaster Response",
      existing: "Monitoring and alerts are often separated from planning",
      qflare: "Connects flood intelligence with response planning",
    },
    {
      feature: "Data Quality",
      existing: "May require manual checking",
      qflare: "Automated validation, duplicate detection and quality analysis",
    },
    {
      feature: "End-to-End Workflow",
      existing: "Multiple independent systems",
      qflare: "Data → Forecast → Risk → Optimization → Response",
    },
  ];

  const innovationGaps = [
    "Fragmentation between flood data, forecasting, GIS and response systems",
    "Limited integration of heterogeneous flood datasets",
    "Insufficient automated data-quality processing",
    "Limited connection between flood prediction and resource optimization",
    "Limited experimentation with quantum optimization for flood-management decisions",
    "Lack of a unified end-to-end flood intelligence workflow",
  ];

  return (
    <div className="existing-solutions-page">
      {/* PAGE HEADER */}

      <div className="page-heading">
        <div>
          <h1>Existing Solutions</h1>

          <p>
            Analysis of current flood-management technologies,
            their limitations, and the proposed Q-FLARE approach.
          </p>
        </div>
      </div>

      {/* CURRENT SOLUTIONS */}

      <section className="solutions-section">
        <div className="section-heading">
          <h2>Current Flood Management Solutions</h2>

          <p>
            Existing technologies used for flood monitoring,
            prediction, mapping, and management.
          </p>
        </div>

        <div className="solutions-grid">
          {existingSolutions.map((solution) => (
            <div
              className="solution-card"
              key={solution.name}
            >
              <h3>{solution.name}</h3>

              <div className="solution-field">
                <span>Technology</span>
                <strong>{solution.technology}</strong>
              </div>

              <div className="solution-field">
                <span>Purpose</span>
                <strong>{solution.purpose}</strong>
              </div>

              <div className="solution-limitation">
                <span>Limitation</span>
                <p>{solution.limitation}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* LIMITATIONS */}

      <section className="solutions-section">
        <div className="section-heading">
          <h2>Limitations of Existing Approaches</h2>

          <p>
            Key gaps that motivate an integrated flood-intelligence
            platform.
          </p>
        </div>

        <div className="limitations-grid">
          {[
            "Data sources are often distributed across different systems.",
            "Flood monitoring, prediction, mapping and response planning may operate independently.",
            "Data-quality problems can affect downstream analysis.",
            "Prediction does not automatically translate into optimized resource allocation.",
            "Different technologies may require separate interfaces and workflows.",
            "Real-time decision support can require integration of several independent data sources.",
          ].map((limitation, index) => (
            <div
              className="limitation-card"
              key={index}
            >
              <span className="limitation-number">
                {index + 1}
              </span>

              <p>{limitation}</p>
            </div>
          ))}
        </div>
      </section>

      {/* PROPOSED SOLUTION */}

      <section className="proposed-solution-section">
        <div className="section-heading">
          <h2>Q-FLARE Proposed Solution</h2>

          <p>
            Quantum-AI Flood Forecasting & Disaster-Response
            Optimization Platform.
          </p>
        </div>

        <div className="qflare-overview">
          <div className="qflare-description">
            <h3>Integrated Flood Intelligence</h3>

            <p>
              Q-FLARE is designed as an integrated platform that
              connects flood-related data management, forecasting,
              GIS-based analysis, optimization and disaster-response
              workflows.
            </p>

            <p>
              The platform creates a continuous pipeline from
              validated data to prediction, risk analysis,
              optimization and response planning.
            </p>
          </div>

          <div className="workflow-card">
            <div className="workflow-step">
              <span>01</span>
              <strong>Data</strong>
              <small>Collect & validate</small>
            </div>

            <div className="workflow-arrow">→</div>

            <div className="workflow-step">
              <span>02</span>
              <strong>Forecast</strong>
              <small>Predict flood conditions</small>
            </div>

            <div className="workflow-arrow">→</div>

            <div className="workflow-step">
              <span>03</span>
              <strong>Risk</strong>
              <small>Analyze impact</small>
            </div>

            <div className="workflow-arrow">→</div>

            <div className="workflow-step">
              <span>04</span>
              <strong>Optimize</strong>
              <small>Generate decisions</small>
            </div>

            <div className="workflow-arrow">→</div>

            <div className="workflow-step">
              <span>05</span>
              <strong>Response</strong>
              <small>Support action planning</small>
            </div>
          </div>
        </div>
      </section>

      {/* TECHNOLOGY COMPARISON */}

      <section className="solutions-section">
        <div className="section-heading">
          <h2>Technology Comparison</h2>

          <p>
            Comparison between common existing approaches and the
            planned Q-FLARE architecture.
          </p>
        </div>

        <div className="comparison-table-wrapper">
          <table className="comparison-table">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Existing Approaches</th>
                <th>Q-FLARE</th>
              </tr>
            </thead>

            <tbody>
              {technologyComparison.map((item) => (
                <tr key={item.feature}>
                  <td>
                    <strong>{item.feature}</strong>
                  </td>

                  <td>{item.existing}</td>

                  <td>{item.qflare}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* INNOVATION GAP */}

      <section className="solutions-section">
        <div className="section-heading">
          <h2>Innovation Gap</h2>

          <p>
            Areas where Q-FLARE aims to provide a more integrated
            workflow.
          </p>
        </div>

        <div className="innovation-grid">
          {innovationGaps.map((gap, index) => (
            <div
              className="innovation-card"
              key={index}
            >
              <div className="innovation-icon">
                {index + 1}
              </div>

              <p>{gap}</p>
            </div>
          ))}
        </div>
      </section>

      {/* SUMMARY */}

      <section className="qflare-summary">
        <h2>Q-FLARE at a Glance</h2>

        <p>
          Instead of treating flood data, forecasting, spatial
          intelligence and response planning as isolated activities,
          Q-FLARE is designed to connect them into one decision-support
          workflow.
        </p>

        <div className="summary-flow">
          <span>Validated Data</span>
          <span>→</span>
          <span>Forecasting</span>
          <span>→</span>
          <span>Risk Analysis</span>
          <span>→</span>
          <span>Optimization</span>
          <span>→</span>
          <span>Response Planning</span>
        </div>
      </section>
    </div>
  );
}

export default ExistingSolutions;