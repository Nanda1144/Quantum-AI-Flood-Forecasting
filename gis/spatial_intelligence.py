import pandas as pd
def calculate_sensor_priority(
    flood_risk,
    population_risk,
    dam_proximity,
    road_access
):
    """
    Spatial Intelligence based sensor priority calculation.

    Weights:
    Flood Risk         = 40%
    Population Risk    = 25%
    Dam Proximity      = 20%
    Road Accessibility = 15%

    All input values should be between 0 and 100.
    """

    score = (
        flood_risk * 0.40
        + population_risk * 0.25
        + dam_proximity * 0.20
        + road_access * 0.15
    )

    return round(score, 2)


def classify_priority(score):
    """
    Convert the numerical priority score into a category.
    """

    if score >= 80:
        return "High"

    elif score >= 60:
        return "Medium"

    else:
        return "Low"


def generate_priority_reason(
    flood_risk,
    population_risk,
    dam_proximity,
    road_access
):
    """
    Generate a simple explanation for why a sensor
    received its priority score.
    """

    reasons = []

    if flood_risk >= 70:
        reasons.append("High flood risk")
    elif flood_risk >= 40:
        reasons.append("Moderate flood risk")

    if population_risk >= 70:
        reasons.append("High population risk")
    elif population_risk >= 40:
        reasons.append("Moderate population risk")

    if dam_proximity >= 70:
        reasons.append("Near dam")
    elif dam_proximity >= 40:
        reasons.append("Moderately near dam")

    if road_access >= 70:
        reasons.append("Good road access")
    elif road_access < 40:
        reasons.append("Limited road access")

    if not reasons:
        reasons.append("Lower overall spatial risk")

    return ", ".join(reasons)


def optimize_sensors(candidates, number_of_sensors=2):
    """
    Select high-priority sensors while maintaining
    coverage across different river basins.
    """

    candidates = candidates.sort_values(
        by="priority_score",
        ascending=False
    ).copy()

    selected = []

    # Select the highest-priority sensor from each basin
    for basin in candidates["basin"].dropna().unique():
        basin_candidates = candidates[
            candidates["basin"] == basin
        ]

        if not basin_candidates.empty:
            selected.append(basin_candidates.iloc[0])

    # Convert selected sensors to DataFrame
    optimized = pd.DataFrame(selected)

    # If more sensors are requested, fill remaining slots
    remaining = candidates[
        ~candidates["id"].isin(optimized["id"])
    ]

    remaining_slots = number_of_sensors - len(optimized)

    if remaining_slots > 0:
        optimized = pd.concat(
            [
                optimized,
                remaining.head(remaining_slots)
            ],
            ignore_index=True
        )

    return optimized.head(number_of_sensors)