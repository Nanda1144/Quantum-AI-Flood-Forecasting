def calculate_sensor_priority(
    flood_risk,
    population_risk,
    dam_proximity,
    road_access
):
    """
    Prototype sensor priority calculation.

    Flood Risk         = 40%
    Population Risk    = 25%
    Dam Proximity      = 20%
    Road Accessibility = 15%
    """

    score = (
        flood_risk * 0.40
        + population_risk * 0.25
        + dam_proximity * 0.20
        + road_access * 0.15
    )

    return round(score, 2)


def classify_priority(score):

    if score >= 80:
        return "High"

    elif score >= 60:
        return "Medium"

    else:
        return "Low"


def optimize_sensors(candidates, number_of_sensors=2):
    """
    Select the highest-priority candidate sensors.

    The candidates must already contain:
    - priority_score
    - priority_level
    """

    optimized = candidates.sort_values(
        by="priority_score",
        ascending=False
    ).head(number_of_sensors).copy()

    return optimized