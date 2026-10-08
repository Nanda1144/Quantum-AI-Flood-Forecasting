from flask import Flask, request
import pandas as pd
import folium
import geopandas as gpd

from spatial_intelligence import (
    calculate_sensor_priority,
    classify_priority,
    generate_priority_reason,
    optimize_sensors
)

app = Flask(__name__)


# ============================================================
# PATHS
# ============================================================

DATA_FOLDER = "gis/data"

RIVER_NETWORK_GEOJSON = (
    "gis/data/geographic/krishna_godavari_river_network.geojson"
)

BASIN_GEOJSON = (
    "gis/data/geographic/krishna_godavari.geojson"
)


# ============================================================
# LOAD CSV DATA
# ============================================================

dams = pd.read_csv(f"{DATA_FOLDER}/dams.csv")
rivers = pd.read_csv(f"{DATA_FOLDER}/rivers.csv")
reservoirs = pd.read_csv(f"{DATA_FOLDER}/reservoirs.csv")
flood_zones = pd.read_csv(f"{DATA_FOLDER}/flood_zones.csv")
elevation = pd.read_csv(f"{DATA_FOLDER}/elevation.csv")
population = pd.read_csv(f"{DATA_FOLDER}/population.csv")
roads = pd.read_csv(f"{DATA_FOLDER}/roads.csv")
blocked_roads = pd.read_csv(f"{DATA_FOLDER}/blocked_roads.csv")
hospitals = pd.read_csv(f"{DATA_FOLDER}/hospitals.csv")
shelters = pd.read_csv(f"{DATA_FOLDER}/shelters.csv")
sensors = pd.read_csv(f"{DATA_FOLDER}/sensors.csv")
candidate_sensors = pd.read_csv(
    f"{DATA_FOLDER}/candidate_sensors.csv"
)


# ============================================================
# LOAD REAL CWC BASIN DATA
# ============================================================

basin_boundaries = gpd.read_file(BASIN_GEOJSON)

# Make sure map coordinates are Latitude / Longitude
basin_boundaries = basin_boundaries.to_crs(epsg=4326)


# ============================================================
# LOAD OFFICIAL CWC RIVER NETWORK
# ============================================================

river_network = gpd.read_file(
    RIVER_NETWORK_GEOJSON
)

# Make sure river coordinates are Latitude / Longitude
river_network = river_network.to_crs(epsg=4326)


# ============================================================
# SENSOR PRIORITY CALCULATION
# ============================================================

candidate_sensors["priority_score"] = candidate_sensors.apply(
    lambda row: calculate_sensor_priority(
        row["flood_risk"],
        row["population_risk"],
        row["dam_proximity"],
        row["road_access"]
    ),
    axis=1
)


candidate_sensors["priority_reason"] = candidate_sensors.apply(
    lambda row: generate_priority_reason(
        row["flood_risk"],
        row["population_risk"],
        row["dam_proximity"],
        row["road_access"]
    ),
    axis=1
)


candidate_sensors["priority_level"] = candidate_sensors[
    "priority_score"
].apply(classify_priority)


# ============================================================
# AUTOMATIC SENSOR OPTIMIZATION
# ============================================================

optimized_sensors = optimize_sensors(
    candidate_sensors,
    number_of_sensors=2
)


# ============================================================
# BASIN FILTER
# ============================================================

def filter_basin(dataframe, basin):

    if basin == "All":
        return dataframe

    if "basin" not in dataframe.columns:
        return dataframe

    return dataframe[
        dataframe["basin"].astype(str).str.lower()
        == basin.lower()
    ].copy()


def filter_basin_boundaries(dataframe, basin):

    if basin == "All":
        return dataframe

    return dataframe[
        dataframe["ba_name"].astype(str).str.lower()
        == basin.lower()
    ].copy()


# ============================================================
# MAIN ROUTE
# ============================================================

@app.route("/")
def dashboard():

    basin = request.args.get("basin", "All")


    # --------------------------------------------------------
    # FILTER CSV DATA
    # --------------------------------------------------------

    filtered_dams = filter_basin(
        dams,
        basin
    )

    filtered_reservoirs = filter_basin(
        reservoirs,
        basin
    )

    filtered_flood_zones = filter_basin(
        flood_zones,
        basin
    )

    filtered_elevation = filter_basin(
        elevation,
        basin
    )

    filtered_population = filter_basin(
        population,
        basin
    )

    filtered_roads = filter_basin(
        roads,
        basin
    )

    filtered_blocked_roads = filter_basin(
        blocked_roads,
        basin
    )

    filtered_hospitals = filter_basin(
        hospitals,
        basin
    )

    filtered_shelters = filter_basin(
        shelters,
        basin
    )

    filtered_sensors = filter_basin(
        sensors,
        basin
    )

    filtered_candidates = filter_basin(
        candidate_sensors,
        basin
    )

    filtered_optimized = filter_basin(
        optimized_sensors,
        basin
    )


    # --------------------------------------------------------
    # FILTER REAL CWC BASIN BOUNDARIES
    # --------------------------------------------------------

    filtered_basin_boundaries = filter_basin_boundaries(
        basin_boundaries,
        basin
    )


    # --------------------------------------------------------
    # FILTER OFFICIAL CWC RIVER NETWORK
    # --------------------------------------------------------

    if basin == "All":

        # Keep only the Krishna and Godavari basin areas
        # because these are the project scope.

        project_basins = basin_boundaries[
            basin_boundaries["ba_name"]
            .astype(str)
            .str.lower()
            .isin(["krishna", "godavari"])
        ]

        if not project_basins.empty:

            filtered_river_network = gpd.clip(
                river_network,
                project_basins
            )

        else:

            filtered_river_network = river_network.copy()

    else:

        if not filtered_basin_boundaries.empty:

            filtered_river_network = gpd.clip(
                river_network,
                filtered_basin_boundaries
            )

        else:

            filtered_river_network = (
                river_network.iloc[0:0].copy()
            )


    # ========================================================
    # CREATE MAP
    # ========================================================

    m = folium.Map(
        location=[16.8, 80.5],
        zoom_start=7,
        control_scale=True
    )


    # ========================================================
    # REAL CWC BASIN BOUNDARIES
    # ========================================================

    basin_layer = folium.FeatureGroup(
        name="Real CWC Basin Boundaries",
        show=True
    )


    folium.GeoJson(
        filtered_basin_boundaries.to_json(),

        name="CWC Krishna and Godavari Basins",

        style_function=lambda feature: {
            "color": "#00FFFF",
            "weight": 5,
            "opacity": 1,
            "fillColor": "#00FFFF",
            "fillOpacity": 0.08
        },

        highlight_function=lambda feature: {
            "color": "#FFFF00",
            "weight": 7,
            "opacity": 1,
            "fillOpacity": 0.15
        },

        tooltip=folium.GeoJsonTooltip(
            fields=["ba_name"],
            aliases=["CWC Basin:"],
            sticky=True
        )

    ).add_to(basin_layer)


    basin_layer.add_to(m)


    # ========================================================
    # OFFICIAL CWC RIVER NETWORK
    # ========================================================

    river_network_layer = folium.FeatureGroup(
        name="Official CWC River Network",
        show=True
    )


    if not filtered_river_network.empty:

        folium.GeoJson(
            filtered_river_network.to_json(),

            name="CWC River Network",

            style_function=lambda feature: {
                "color": "#0066FF",
                "weight": 2.5,
                "opacity": 0.9
            },

            highlight_function=lambda feature: {
                "color": "#00FFFF",
                "weight": 4,
                "opacity": 1
            },

            tooltip=folium.GeoJsonTooltip(
                fields=[
                    "rivname"
                ],
                aliases=[
                    "River:"
                ],
                sticky=True
            )

        ).add_to(river_network_layer)


    river_network_layer.add_to(m)


    # ========================================================
    # DAMS
    # ========================================================

    dam_layer = folium.FeatureGroup(
        name="Dams",
        show=True
    )


    for _, row in filtered_dams.iterrows():

        folium.Marker(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            popup=folium.Popup(
                f"""
                <b>Dam:</b> {row['name']}<br>
                <b>Basin:</b> {row['basin']}<br>
                <b>Risk:</b> {row.get('risk', 'N/A')}
                """,
                max_width=300
            ),

            icon=folium.Icon(
                color="blue",
                icon="tint",
                prefix="fa"
            )

        ).add_to(dam_layer)


    dam_layer.add_to(m)


    # ========================================================
    # RESERVOIRS
    # ========================================================

    reservoir_layer = folium.FeatureGroup(
        name="Reservoirs",
        show=True
    )


    for _, row in filtered_reservoirs.iterrows():

        folium.CircleMarker(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            radius=8,

            color="#00AA44",
            fill=True,
            fill_color="#00AA44",
            fill_opacity=0.9,

            popup=folium.Popup(
                f"""
                <b>Reservoir:</b> {row['name']}<br>
                <b>Basin:</b> {row['basin']}
                """,
                max_width=300
            )

        ).add_to(reservoir_layer)


    reservoir_layer.add_to(m)


    # ========================================================
    # FLOOD ZONES
    # ========================================================

    flood_layer = folium.FeatureGroup(
        name="Flood Zones",
        show=True
    )


    for _, row in filtered_flood_zones.iterrows():

        risk = str(
            row.get("risk", "Medium")
        ).lower()


        if risk == "high":
            color = "red"

        elif risk == "medium":
            color = "orange"

        else:
            color = "green"


        folium.Circle(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            radius=10000,

            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.25,

            popup=folium.Popup(
                f"""
                <b>Flood Zone:</b>
                {row.get('name', 'Flood Zone')}<br>

                <b>Risk:</b>
                {row.get('risk', 'N/A')}<br>

                <b>Basin:</b>
                {row.get('basin', 'N/A')}
                """,
                max_width=300
            )

        ).add_to(flood_layer)


    flood_layer.add_to(m)


    # ========================================================
    # ELEVATION
    # ========================================================

    elevation_layer = folium.FeatureGroup(
        name="Elevation",
        show=False
    )


    for _, row in filtered_elevation.iterrows():

        folium.CircleMarker(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            radius=6,

            color="#8B4513",
            fill=True,
            fill_color="#8B4513",
            fill_opacity=0.8,

            popup=folium.Popup(
                f"""
                <b>Elevation:</b>
                {row.get('elevation', 'N/A')} m<br>

                <b>Basin:</b>
                {row.get('basin', 'N/A')}
                """,
                max_width=300
            )

        ).add_to(elevation_layer)


    elevation_layer.add_to(m)


    # ========================================================
    # POPULATION
    # ========================================================

    population_layer = folium.FeatureGroup(
        name="Population",
        show=False
    )


    for _, row in filtered_population.iterrows():

        folium.Circle(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            radius=8000,

            color="purple",
            fill=True,
            fill_color="purple",
            fill_opacity=0.25,

            popup=folium.Popup(
                f"""
                <b>Population:</b>
                {row.get('population', 'N/A')}<br>

                <b>Basin:</b>
                {row.get('basin', 'N/A')}
                """,
                max_width=300
            )

        ).add_to(population_layer)


    population_layer.add_to(m)


    # ========================================================
    # ROADS
    # ========================================================

    road_layer = folium.FeatureGroup(
        name="Roads",
        show=False
    )


    for _, row in filtered_roads.iterrows():

        folium.CircleMarker(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            radius=5,

            color="gray",
            fill=True,
            fill_color="gray",
            fill_opacity=0.8,

            popup=folium.Popup(
                f"""
                <b>Road:</b>
                {row.get('name', 'Road')}<br>

                <b>Basin:</b>
                {row.get('basin', 'N/A')}
                """,
                max_width=300
            )

        ).add_to(road_layer)


    road_layer.add_to(m)


    # ========================================================
    # BLOCKED ROADS
    # ========================================================

    blocked_road_layer = folium.FeatureGroup(
        name="Blocked Roads",
        show=False
    )


    for _, row in filtered_blocked_roads.iterrows():

        folium.Marker(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            popup=folium.Popup(
                f"""
                <b>Blocked Road</b><br>

                <b>Location:</b>
                {row.get('name', 'Unknown')}<br>

                <b>Reason:</b>
                {row.get('reason', 'Flooding')}
                """,
                max_width=300
            ),

            icon=folium.Icon(
                color="red",
                icon="warning-sign",
                prefix="glyphicon"
            )

        ).add_to(blocked_road_layer)


    blocked_road_layer.add_to(m)


    # ========================================================
    # HOSPITALS
    # ========================================================

    hospital_layer = folium.FeatureGroup(
        name="Hospitals",
        show=False
    )


    for _, row in filtered_hospitals.iterrows():

        folium.Marker(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            popup=folium.Popup(
                f"""
                <b>Hospital:</b>
                {row.get('name', 'Hospital')}<br>

                <b>Basin:</b>
                {row.get('basin', 'N/A')}
                """,
                max_width=300
            ),

            icon=folium.Icon(
                color="purple",
                icon="plus",
                prefix="fa"
            )

        ).add_to(hospital_layer)


    hospital_layer.add_to(m)


    # ========================================================
    # SHELTERS
    # ========================================================

    shelter_layer = folium.FeatureGroup(
        name="Shelters",
        show=False
    )


    for _, row in filtered_shelters.iterrows():

        folium.Marker(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            popup=folium.Popup(
                f"""
                <b>Shelter:</b>
                {row.get('name', 'Shelter')}<br>

                <b>Basin:</b>
                {row.get('basin', 'N/A')}
                """,
                max_width=300
            ),

            icon=folium.Icon(
                color="darkred",
                icon="home",
                prefix="fa"
            )

        ).add_to(shelter_layer)


    shelter_layer.add_to(m)


    # ========================================================
    # EXISTING SENSORS
    # ========================================================

    sensor_layer = folium.FeatureGroup(
        name="Existing Sensors",
        show=True
    )


    for _, row in filtered_sensors.iterrows():

        folium.CircleMarker(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            radius=7,

            color="#0066FF",
            fill=True,
            fill_color="#0066FF",
            fill_opacity=1,

            popup=folium.Popup(
                f"""
                <b>Existing Sensor</b><br>

                <b>ID:</b>
                {row.get('name', row.get('id', 'Sensor'))}<br>

                <b>Basin:</b>
                {row.get('basin', 'N/A')}
                """,
                max_width=300
            )

        ).add_to(sensor_layer)


    sensor_layer.add_to(m)


    # ========================================================
    # CANDIDATE SENSORS
    # ========================================================

    candidate_layer = folium.FeatureGroup(
        name="Candidate Sensors",
        show=False
    )


    for _, row in filtered_candidates.iterrows():

        folium.CircleMarker(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            radius=9,

            color="#FF8800",
            fill=True,
            fill_color="#FF8800",
            fill_opacity=1,

            popup=folium.Popup(
                f"""
                <b>Candidate Sensor</b><br>

                <b>ID:</b>
                {row.get('name', row.get('id', 'Candidate'))}<br>

                <b>Priority Score:</b>
                {row['priority_score']}<br>

                <b>Priority:</b>
                {row['priority_level']}<br>

                <b>Flood Risk:</b>
                {row['flood_risk']}<br>

                <b>Population Risk:</b>
                {row['population_risk']}<br>

                <b>Dam Proximity:</b>
                {row['dam_proximity']}<br>

                <b>Road Access:</b>
                {row['road_access']}
                """,
                max_width=350
            )

        ).add_to(candidate_layer)


    candidate_layer.add_to(m)


    # ========================================================
    # OPTIMIZED SENSORS
    # ========================================================

    optimized_layer = folium.FeatureGroup(
        name="Optimized Sensors",
        show=True
    )


    for _, row in filtered_optimized.iterrows():

        folium.Marker(
            location=[
                row["latitude"],
                row["longitude"]
            ],

            popup=folium.Popup(
                f"""
                <b>Optimized Sensor</b><br>

                <b>ID:</b>
                {row.get('name', row.get('id', 'Optimized'))}<br>

                <b>Priority Score:</b>
                {row['priority_score']}<br>

                <b>Priority:</b>
                {row['priority_level']}<br><br>

                <b>Why selected?</b><br>

                This location received a high spatial
                priority score based on flood risk,
                population risk, dam proximity and
                road accessibility.
                """,
                max_width=400
            ),

            icon=folium.Icon(
                color="purple",
                icon="star",
                prefix="fa"
            )

        ).add_to(optimized_layer)


    optimized_layer.add_to(m)


    # ========================================================
    # BASIN FILTER PANEL
    # ========================================================

    filter_html = f"""
    <div style="
        position: fixed;
        top: 20px;
        left: 60px;
        z-index: 9999;
        background: white;
        padding: 10px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        font-family: Arial;
    ">

        <b>River Basin:</b>

        <select
            onchange="window.location.href='/?basin=' + this.value"
            style="
                margin-left: 5px;
                padding: 5px;
            "
        >

            <option value="All"
                {'selected' if basin == 'All' else ''}>
                All
            </option>

            <option value="Krishna"
                {'selected' if basin == 'Krishna' else ''}>
                Krishna
            </option>

            <option value="Godavari"
                {'selected' if basin == 'Godavari' else ''}>
                Godavari
            </option>

        </select>

    </div>
    """


    m.get_root().html.add_child(
        folium.Element(filter_html)
    )


    # ========================================================
    # LEGEND
    # ========================================================

    legend_html = '''
    <div style="
        position: fixed;
        bottom: 30px;
        left: 30px;
        z-index: 9999;
        background: white;
        padding: 12px;
        border: 2px solid #444;
        border-radius: 8px;
        font-family: Arial;
        font-size: 13px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    ">

        <b>Q-FLARE GIS Legend</b><br><br>

        <span style="color:#00FFFF;">▰</span>
        Real CWC Basin Boundary<br>

        <span style="color:#0066FF;">━</span>
        Official CWC River Network<br>

        <span style="color:blue;">●</span>
        Dams / Existing Sensors<br>

        <span style="color:#00AA44;">●</span>
        Reservoirs<br>

        <span style="color:red;">●</span>
        High Flood Risk<br>

        <span style="color:orange;">●</span>
        Medium Flood Risk<br>

        <span style="color:green;">●</span>
        Low Flood Risk<br>

        <span style="color:purple;">●</span>
        Population / Hospitals<br>

        <span style="color:#FF8800;">●</span>
        Candidate Sensors<br>

        <span style="color:purple;">★</span>
        Optimized Sensors

    </div>
    '''


    m.get_root().html.add_child(
        folium.Element(legend_html)
    )


    # ========================================================
    # LAYER CONTROL
    # ========================================================

    folium.LayerControl(
        collapsed=False
    ).add_to(m)


    # ========================================================
    # RETURN MAP
    # ========================================================

    return m.get_root().render()


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )