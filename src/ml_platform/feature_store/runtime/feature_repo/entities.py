"""
feature_repo/entities.py
=========================
Feast entity definitions for the ML Platform feature store.

An Entity represents the primary key used to look up features. The customer
entity joins feature views on the `entity_id` column, which must be present
in every entity DataFrame passed to get_historical_features().

Extension path (road-to-prod §1):
  Additional entities (e.g. product, session) are added here. Each entity
  gets its own join key column in the entity DataFrame.
"""

from feast import Entity, ValueType

# ── Customer entity ────────────────────────────────────────────────────────

customer = Entity(
    name="customer",
    value_type=ValueType.STRING,
    join_keys=["entity_id"],
    description=(
        "A customer identified by entity_id. "
        "Join key for all customer-level feature views."
    ),
)
