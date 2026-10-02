# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction -
# Nanda & Navya). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Static checks on migration `011_navya_hydro_observation_domains`.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
This file reads SQL **as text** and asserts things about it. It does not open a
database connection, and it does not execute a statement.

No PostgreSQL server or `psql` binary was available in the Phase 1 environment,
so migration 011 is **static-checked only**. That is a weaker statement than the
one `02_Architecture/ASSUMPTIONS_AND_LIMITATIONS.md` records for migration 010
("verified 19/19 against local PostgreSQL 17.10"), and the header of 011 says so
in the same terms. Anyone applying 011 must run it against a real instance, and
that run — not this file — is the verification.

What these tests are actually good for
--------------------------------------
Text assertions catch the failure modes that are cheap to make and expensive to
discover late: a typo in a domain name, a CHECK that permits NaN, a constraint
that permits the exact dishonesty the project exists to prevent, a vocabularysthat silently drifts from the Python one, an `ALTER` of somebody else's table.
A text assertion cannot prove the SQL parses or that PostgreSQL accepts it. It
proves the intent is written down, and that the intent has not quietly changed.

**All identifiers in this file are structural**: column, table and constraint
names. No rainfall value, water level, station identifier, threshold, coordinate,
population figure or flood event appears in this migration, and none is asserted
here — only that none is present.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.engines.hydro.contract import (
    FORECAST_CONTRACT_VERSION,
    SUPPORTED_PRIORITIES,
    SUPPORTED_RISK_LEVELS,
)
from app.engines.hydro.datasets import SCHEMA_VERSION
from app.engines.hydro.domains import (
    DATA_DOMAINS,
    MEASUREMENT_DOMAINS,
    QUALITY_STATUSES,
    RISK_STATUSES,
)
from app.engines.hydro.provenance import SYNTHETIC_DATA_DISCLAIMER

#: Repository root, resolved from this file so the checks do not depend on the
#: process working directory (tests are run from `ai-service/`).
REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "database" / "migrations"

UP_PATH = MIGRATIONS / "011_navya_hydro_observation_domains.up.sql"
DOWN_PATH = MIGRATIONS / "011_navya_hydro_observation_domains.down.sql"

#: Objects migration 011 introduces. Asserted as a set so a table added later
#: without a matching DROP in the down migration fails here rather than at the
#: moment someone needs to roll back.
OWNED_TABLES = (
    "navya_dataset_catalog",
    "navya_observation",
    "navya_observation_measurement",
    "navya_flood_event",
    "navya_risk_score",
    "navya_data_quality_report",
)

#: Tables owned by other people. Migration 011 may reference them; it may not
#: change them.
TEAM_OBJECTS = (
    "forecasts",
    "model_metrics",
    "model_versions",
    "users",
    "alerts",
    "devices",
    "sensor_readings",
)


def _read(path: Path) -> str:
    if not path.exists():
        pytest.fail(f"migration file is missing: {path}")
    return path.read_text(encoding="utf-8")


def _statements(sql: str) -> list[str]:
    """Split on `;` at end of line, dropping comments.

    Deliberately simple: this is a text fixture with no string literals holding a
    semicolon, and a real SQL parser would be a dependency this project does not
    need in order to assert that a CHECK exists.
    """
    lines = [
        line
        for line in sql.splitlines()
        if not line.strip().startswith("--")
    ]
    return [
        statement.strip()
        for statement in "\n".join(lines).split(";")
        if statement.strip()
    ]


def _code(sql: str) -> str:
    """The SQL with comment lines removed.

    Several assertions below are about what the schema *declares*. A word that
    appears only in a comment explaining why the thing is absent is exactly the
    word that must be allowed there — so the two are separated before searching.
    """
    return "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )


@pytest.fixture(scope="module")
def up_sql() -> str:
    return _read(UP_PATH)


@pytest.fixture(scope="module")
def down_sql() -> str:
    return _read(DOWN_PATH)


# --------------------------------------------------------------------------- #
# Honesty about what was verified
# --------------------------------------------------------------------------- #


def test_the_up_migration_states_that_it_was_not_executed(up_sql: str):
    """The claim in the header must be *weaker* than 010's, because it is true.

    If a PostgreSQL server ever becomes available, this test should be deleted
    rather than edited — the honest fix is to run the migration and say so.
    """
    assert "VERIFICATION STATUS" in up_sql
    assert "NOT executed" in up_sql or "not executed" in up_sql
    assert "psql" in up_sql


def test_the_up_migration_does_not_claim_a_server_verification(up_sql: str):
    """Guards against a copy-pasted verification claim from migration 010."""
    assert "verified against" not in up_sql.lower()
    assert "17.10" not in up_sql


def test_this_test_module_does_not_claim_to_be_a_database_test():
    """The module docstring is the honest description; keep it honest."""
    source = _read(Path(__file__))
    assert "static-checked only" in source
    assert "does not open a database" in source


# --------------------------------------------------------------------------- #
# Ownership
# --------------------------------------------------------------------------- #


def test_only_navya_owned_tables_are_created(up_sql: str):
    created = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", up_sql)
    assert tuple(sorted(created)) == tuple(sorted(OWNED_TABLES))


def test_no_team_table_is_altered_dropped_or_truncated(up_sql: str):
    """`CREATE TABLE`, `CREATE INDEX`, `COMMENT ON VIEW` — nothing else mutates."""
    mutating = re.findall(
        r"^\s*(ALTER\s+TABLE|DROP\s+TABLE|DROP\s+INDEX|TRUNCATE|INSERT\s+INTO|UPDATE\s+\w+\s+SET)\b",
        up_sql,
        re.IGNORECASE | re.MULTILINE,
    )
    assert mutating == []


def test_no_team_object_is_even_named_in_a_mutating_statement(up_sql: str):
    for table in TEAM_OBJECTS:
        for statement in _statements(up_sql):
            head = statement.split()[0].upper()
            assert not (
                head in ("ALTER", "DROP", "INSERT", "UPDATE", "TRUNCATE")
                and table in statement
            ), f"{table} appears in a mutating statement: {statement[:80]}"


def test_the_migration_is_additive_only(up_sql: str):
    """Everything it does is IF NOT EXISTS / OR REPLACE, so re-running is a no-op.

    `CREATE CONSTRAINT TRIGGER` is the one exception and is excluded here:
    PostgreSQL gives it no IF NOT EXISTS form, so it is guarded by a preceding
    `DROP TRIGGER IF EXISTS` instead, which `test_the_trigger_is_recreatable`
    checks.
    """
    creates = [
        statement
        for statement in _statements(up_sql)
        if statement.upper().startswith("CREATE")
        and not statement.upper().startswith("CREATE CONSTRAINT TRIGGER")
    ]
    assert creates, "expected CREATE statements"
    for statement in creates:
        head = " ".join(statement.split()[:6]).upper()
        assert head.startswith("CREATE OR REPLACE") or "IF NOT EXISTS" in head, head


def test_the_function_definition_is_idempotent(up_sql: str):
    """`CREATE FUNCTION` has no IF NOT EXISTS, so it must be CREATE OR REPLACE."""
    assert re.search(
        r"CREATE OR REPLACE FUNCTION navya_observation_has_measurement\(\)",
        up_sql,
    )


def test_the_trigger_is_recreatable(up_sql: str):
    """`CREATE TRIGGER` has no IF NOT EXISTS either, so it is preceded by a DROP
    of itself only — never of a constraint that is not this migration's own."""
    assert "DROP TRIGGER IF EXISTS trg_navya_observation_has_measurement ON navya_observation;" in up_sql
    for line in up_sql.splitlines():
        if "DROP TRIGGER IF EXISTS" in line:
            assert line.strip().startswith("DROP TRIGGER IF EXISTS trg_navya_"), line


def test_the_foreign_keys_are_references_not_modifications(up_sql: str):
    """The only team object touched at all is referenced, never changed."""
    assert "REFERENCES navya_forecast_provenance (forecast_id)" in up_sql
    assert "ALTER TABLE forecasts" not in up_sql
    assert "ALTER TABLE model_metrics" not in up_sql


# --------------------------------------------------------------------------- #
# Reversibility
# --------------------------------------------------------------------------- #


def test_every_table_created_is_dropped_by_the_down_migration(up_sql: str, down_sql: str):
    for table in OWNED_TABLES:
        assert f"DROP TABLE IF EXISTS {table};" in down_sql, f"{table} has no DROP"


def test_the_view_is_dropped(up_sql: str, down_sql: str):
    assert "CREATE OR REPLACE VIEW navya_domain_availability" in up_sql
    assert "DROP VIEW IF EXISTS navya_domain_availability;" in down_sql


def test_the_function_and_trigger_are_dropped(up_sql: str, down_sql: str):
    assert "navya_observation_has_measurement" in up_sql
    assert "DROP FUNCTION IF EXISTS navya_observation_has_measurement();" in down_sql
    assert "DROP TRIGGER IF EXISTS trg_navya_observation_has_measurement" in down_sql


def test_the_down_migration_drops_no_team_object(down_sql: str):
    for table in TEAM_OBJECTS:
        assert f"DROP TABLE IF EXISTS {table};" not in down_sql


def test_the_down_migration_does_not_drop_migration_010_tables(down_sql: str):
    """010's tables belong to Navya too, but they are a different phase's schema."""
    for table in ("navya_forecast_provenance", "navya_forecast_evaluation"):
        assert f"DROP TABLE IF EXISTS {table};" not in down_sql


def test_the_down_migration_drops_children_before_parents(down_sql: str):
    order = [
        "navya_observation_measurement",
        "navya_observation",
        "navya_flood_event",
        "navya_risk_score",
        "navya_data_quality_report",
        "navya_dataset_catalog",
    ]
    positions = []
    for table in order:
        index = down_sql.index(f"DROP TABLE IF EXISTS {table};")
        positions.append(index)
    assert positions == sorted(positions)


def test_the_down_migration_is_itself_idempotent(down_sql: str):
    drops = [
        line.strip()
        for line in down_sql.splitlines()
        if line.strip().upper().startswith("DROP ")
    ]
    assert drops
    for statement in drops:
        assert "IF EXISTS" in statement, statement


# --------------------------------------------------------------------------- #
# Anti-fabrication rules, asserted as constraints
# --------------------------------------------------------------------------- #


def test_no_data_is_inserted_by_the_migration(up_sql: str):
    """An empty schema is the honest Phase 1 state; a seeded one would not be."""
    assert "INSERT INTO" not in up_sql.upper()
    assert "COPY " not in up_sql.upper()


#: The exact disclaimer rule, normalised. Restated on every table that carries a
#: `dataset_type`, so a table added later without it fails the count below.
DISCLAIMER_RULE = (
    "(dataset_type = 'real' AND disclaimer IS NULL) "
    "OR (dataset_type IN ('synthetic', 'unknown') AND disclaimer IS NOT NULL "
    "AND disclaimer <> '')"
)

#: The dataset-type vocabulary, as written into every such CHECK.
DATASET_TYPE_RULE = "dataset_type IN ('real', 'synthetic', 'unknown')"


def test_the_disclaimer_rule_is_enforced_on_every_provenance_table(up_sql: str):
    """Same rule as 010, restated per table: non-real must be labelled, real must not."""
    # Four tables carry a dataset_type: the catalogue, observations, flood events
    # and risk scores. `navya_observation_measurement` and
    # `navya_data_quality_report` inherit provenance from their subject and
    # deliberately carry none of their own.
    flattened = " ".join(up_sql.split())
    assert flattened.count(DISCLAIMER_RULE) == 4
    # The standalone vocabulary CHECK per table, which is what refuses a
    # `dataset_type` outside the three values at all.
    assert flattened.count(DATASET_TYPE_RULE) == 4
    # Inside the disclaimer rule the vocabulary is the *non-real* pair, because
    # 'real' is the branch handled by the first half of the OR.
    assert flattened.count("dataset_type IN ('synthetic', 'unknown')") == 4


def _table_body(up_sql: str, table: str) -> str:
    """The DDL of one table, comments stripped.

    Comments are removed first because a comment may legitimately contain the
    text `);` — which is exactly what the closing-delimiter search below looks
    for.
    """
    body = _code(up_sql).split(f"CREATE TABLE IF NOT EXISTS {table} (")[1]
    return body.split(");")[0]


def test_every_provenance_table_declares_both_halves_of_the_rule(up_sql: str):
    for table in (
        "navya_dataset_catalog",
        "navya_observation",
        "navya_flood_event",
        "navya_risk_score",
    ):
        body = _table_body(up_sql, table)
        assert "dataset_type" in body, table
        assert "disclaimer" in body, table


def _table_body(up_sql: str, table: str) -> str:
    """The DDL of one table, comments stripped.

    Comments are removed first because a comment may legitimately contain the
    text `);` — which is exactly what the closing-delimiter search below looks
    for.
    """
    body = _code(up_sql).split(f"CREATE TABLE IF NOT EXISTS {table} (")[1]
    return body.split(");")[0]


def test_every_provenance_table_declares_both_halves_of_the_rule(up_sql: str):
    for table in (
        "navya_dataset_catalog",
        "navya_observation",
        "navya_flood_event",
        "navya_risk_score",
    ):
        body = _table_body(up_sql, table)
        assert "dataset_type" in body, table
        assert "disclaimer" in body, table


def test_the_measurement_and_report_tables_carry_no_provenance_of_their_own(up_sql: str):
    """They inherit provenance from their subject. A second, independent
    `dataset_type` on a measurement row could disagree with its parent."""
    for table in ("navya_observation_measurement", "navya_data_quality_report"):
        body = _table_body(up_sql, table)
        assert "disclaimer" not in body, table
        assert "dataset_type" not in body, table


def test_the_disclaimer_relationship_is_not_only_in_python(up_sql: str):
    """`provenance.py` is the source of the sentence; the schema must agree with it."""
    for table in (
        "navya_dataset_catalog",
        "navya_observation",
        "navya_flood_event",
        "navya_risk_score",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table} (" in up_sql
    assert up_sql.count("disclaimer                TEXT") >= 4


def test_nan_and_infinity_are_both_refused_for_measurements(up_sql: str):
    """`value <> 'NaN'` is TRUE for ±Infinity, so the range check is not optional."""
    assert "value <> 'NaN'::DOUBLE PRECISION" in up_sql
    assert "value > '-Infinity'::DOUBLE PRECISION AND value < 'Infinity'::DOUBLE PRECISION" in up_sql


def test_a_measurement_must_declare_a_unit(up_sql: str):
    assert re.search(r"unit\s+TEXT NOT NULL", up_sql)


def test_the_unit_is_not_whitelisted(up_sql: str):
    """A CHECK constraining `unit` to a list would reject `cusecs` and the honest
    `UNDETERMINED (DEMO — no unit assigned)` string. Absence is the requirement."""
    assert not re.search(r"CONSTRAINT chk_navya_\w*unit CHECK", up_sql)


def test_timestamps_are_timestamptz_not_timestamp(up_sql: str):
    """A naive TIMESTAMP is read in the session TimeZone at insert time: the exact
    silent offset shift this schema exists to prevent."""
    instant_columns = re.findall(r"(\w+)\s+TIMESTAMPTZ", up_sql)
    assert {"observed_at", "started_at"} <= set(instant_columns)
    assert not re.search(r"\w+\s+TIMESTAMP(?!TZ)", up_sql)


def test_a_duplicate_identity_is_refused_by_an_index(up_sql: str):
    assert "uq_navya_observation_identity" in up_sql
    assert (
        "ON navya_observation (domain, location_reference, observed_at)" in up_sql
    )
    assert "uq_navya_flood_event_reference" in up_sql
    assert "uq_navya_risk_score_area_instant" in up_sql


def test_a_conflict_is_neither_resolved_nor_collapsed(up_sql: str):
    """No upsert, no ON CONFLICT DO UPDATE, no coalescing of two readings."""
    assert "ON CONFLICT" not in up_sql.upper()
    assert "DISTINCT ON" not in up_sql.upper()


def test_an_unassessed_area_is_null_not_zero(up_sql: str):
    """`risk_score 0.0` would mean "assessed, no risk"; NULL means "not assessed"."""
    assert "risk_score                DOUBLE PRECISION CHECK (" in up_sql
    assert re.search(r"risk_score\s+IS NULL\s*\n?\s*OR \(risk_score >= 0\.0", up_sql)
    # No default on the column: a default would silently turn an unassessed area
    # into a zero-risk area on first insert.
    assert not re.search(r"risk_score[^,\n]*DEFAULT", up_sql)
    assert not re.search(r"DEFAULT\s+0\.0", up_sql)


def test_threshold_approval_requires_evidence(up_sql: str):
    """Silence is not approval — the same rule migration 010 enforces."""
    assert re.search(
        r"CONSTRAINT chk_navya_risk_score_threshold_policy CHECK \(\s*"
        r"\(threshold_policy = 'pending'\)",
        up_sql,
    )
    assert "threshold_source IS NOT NULL AND threshold_source <> ''" in up_sql


def test_a_recorded_risk_score_must_carry_both_halves(up_sql: str):
    assert re.search(r"CONSTRAINT chk_navya_risk_score_recorded CHECK", up_sql)
    assert "status <> 'recorded' OR (risk_score IS NOT NULL AND risk_level IS NOT NULL" in up_sql


def test_a_rate_without_a_window_is_refused(up_sql: str):
    assert "chk_navya_measurement_rate_window" in up_sql
    assert "NOT is_rate OR (measurement_window IS NOT NULL AND measurement_window <> '')" in up_sql


def test_a_quality_summary_must_add_up(up_sql: str):
    assert "records_clean + records_suspect + records_rejected = records_checked" in up_sql
    assert "NOT (quality_status = 'ok' AND records_rejected > 0)" in up_sql


def test_an_empty_observation_is_refused_without_an_impossible_check(up_sql: str):
    """PostgreSQL forbids subqueries in CHECK, so the invariant is a deferred
    constraint trigger. A CHECK containing EXISTS here would not parse."""
    assert "EXISTS (" not in up_sql.split("CREATE OR REPLACE FUNCTION")[0]
    assert "DEFERRABLE INITIALLY DEFERRED" in up_sql
    assert "CREATE CONSTRAINT TRIGGER trg_navya_observation_has_measurement" in up_sql


def test_no_coordinate_or_population_column_is_invented(up_sql: str):
    """The exposure model does not exist, so nothing here stores an asset or a person.

    Checked against the DDL with comments stripped: naming the missing thing in a
    comment is how its absence is documented, and that must stay allowed.
    """
    declarations = _code(up_sql)
    for forbidden in (
        "latitude",
        "longitude",
        "population",
        "elevation",
        "asset_count",
        "coordinates",
    ):
        assert not re.search(rf"\b{forbidden}\s+\w", declarations, re.IGNORECASE), forbidden


def test_no_event_or_station_value_is_hard_coded(up_sql: str):
    """No INSERT, and therefore no invented gauge or flood event."""
    assert "SYNTHETIC-STATION" not in up_sql
    assert "EVENT-" not in up_sql.upper()
    assert "'STATION-" not in up_sql.upper()


# --------------------------------------------------------------------------- #
# The SQL vocabulary cannot drift from the Python one
# --------------------------------------------------------------------------- #


def test_the_measurement_domains_match_the_python_registry(up_sql: str):
    declared = re.search(
        r"CONSTRAINT chk_navya_observation_domain CHECK \(\s*domain IN \((.*?)\)\s*\)",
        up_sql,
        re.DOTALL,
    )
    assert declared, "expected an explicit domain CHECK"
    sql_domains = set(re.findall(r"'(\w+)'", declared.group(1)))
    assert sql_domains == set(MEASUREMENT_DOMAINS)


def test_every_php_domain_appears_in_the_audit_view(up_sql: str):
    """The view writes the domain list out rather than reading it from a table,
    so it is a second copy — and this test is what stops it drifting."""
    view = up_sql.split("CREATE OR REPLACE VIEW navya_domain_availability")[1]
    for domain in DATA_DOMAINS:
        assert f"'{domain}'" in view, domain


def test_the_quality_statuses_match_the_python_vocabulary(up_sql: str):
    declared = re.search(
        r"CONSTRAINT chk_navya_observation_quality_status CHECK \(\s*quality_status IN \((.*?)\)\s*\)",
        up_sql,
        re.DOTALL,
    )
    assert declared
    sql_statuses = set(re.findall(r"'(\w+)'", declared.group(1)))
    assert sql_statuses == set(QUALITY_STATUSES)


def test_the_risk_levels_match_the_forecast_contract(up_sql: str):
    """`contract.SUPPORTED_RISK_LEVELS` is the platform's vocabulary. A different
    list here would mean a risk score the backend cannot read back."""
    declared = re.search(
        r"CONSTRAINT chk_navya_risk_score_level CHECK \(\s*risk_level IS NULL OR risk_level IN \((.*?)\)\s*\)",
        up_sql,
        re.DOTALL,
    )
    assert declared
    sql_levels = set(re.findall(r"'(\w+)'", declared.group(1)))
    assert sql_levels == set(SUPPORTED_RISK_LEVELS)


def test_the_risk_record_statuses_match_the_python_vocabulary(up_sql: str):
    declared = re.search(
        r"CONSTRAINT chk_navya_risk_score_status CHECK \(\s*status IN \((.*?)\)\s*\)",
        up_sql,
        re.DOTALL,
    )
    assert declared
    sql_statuses = set(re.findall(r"'(\w+)'", declared.group(1)))
    assert sql_statuses == set(RISK_STATUSES)


def test_the_schema_version_matches_the_python_one(up_sql: str):
    assert f"DEFAULT '{SCHEMA_VERSION}'" in up_sql


def test_the_forecast_contract_version_is_not_redefined(up_sql: str):
    """010 owns the forecast contract's storage. 011 must not restate its version,
    or a later bump would have to be applied in two places."""
    assert FORECAST_CONTRACT_VERSION not in up_sql


def test_the_disclaimer_text_lives_in_provenance_not_in_sql(up_sql: str):
    """The sentence is imported from `provenance.py`, so there is one copy of it.
    Re-typing it here would create a second, freezable version."""
    assert SYNTHETIC_DATA_DISCLAIMER not in up_sql
    assert "disclaimer" in up_sql


def test_the_priority_vocabulary_is_left_to_the_contract(up_sql: str):
    """`priority` is derived from `risk_level` by `contract.priority_for_risk_level`
    and is not stored, so there is no list here to drift."""
    assert "priority" not in up_sql.lower()
    for level in SUPPORTED_PRIORITIES:
        assert level not in re.findall(r"'(\w+)'", up_sql)


# --------------------------------------------------------------------------- #
# Structural integrity
# --------------------------------------------------------------------------- #


def test_the_migration_pairs_with_its_own_down_file(up_sql: str, down_sql: str):
    assert "011_navya_hydro_observation_domains.up.sql" in up_sql
    assert "011_navya_hydro_observation_domains.down.sql" in down_sql


def test_both_files_carry_the_ownership_header(up_sql: str, down_sql: str):
    for sql in (up_sql, down_sql):
        assert "Owner: Navya" in sql
        assert "Apache-2.0" in sql
        assert "Q-FLARE" in sql


def test_every_statement_ends_with_a_semicolon(up_sql: str, down_sql: str):
    """A missing terminator inside a migration file is the kind of thing that
    silently concatenates two statements when a tool strips comments."""
    for sql in (up_sql, down_sql):
        body = "\n".join(
            line for line in sql.splitlines() if not line.strip().startswith("--")
        ).strip()
        assert body.endswith(";"), body[-60:]


def test_the_tables_the_view_reads_are_created_before_it(up_sql: str):
    assert up_sql.index("CREATE TABLE IF NOT EXISTS navya_observation") < up_sql.index(
        "CREATE OR REPLACE VIEW navya_domain_availability"
    )


#: Navya-owned tables created by migration 010, which 011 references but does not
#: create. Listed explicitly so a new unresolvable reference fails the test below
#: instead of being quietly accepted as "also Navya's".
PRIOR_NAVYA_TABLES = ("navya_forecast_provenance", "navya_forecast_evaluation")


def test_every_referenced_navya_table_exists(up_sql: str):
    for reference in set(re.findall(r"REFERENCES (\w+)", up_sql)):
        assert reference.startswith("navya_"), reference
        if reference in PRIOR_NAVYA_TABLES:
            continue
        assert f"CREATE TABLE IF NOT EXISTS {reference}" in up_sql, reference


def test_the_only_reference_to_010_is_the_forecast_provenance_table(up_sql: str):
    references = set(re.findall(r"REFERENCES (\w+)", up_sql))
    assert references & set(PRIOR_NAVYA_TABLES) == {"navya_forecast_provenance"}


def test_the_audit_view_reports_an_empty_database_honestly(up_sql: str):
    """`present_in_repository` must be derived from the rows, not asserted."""
    assert "(d.count > 0)                                AS present_in_repository" in up_sql
    assert "COALESCE(d.record_count" not in up_sql