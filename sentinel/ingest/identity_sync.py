# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Reconcile the DynamoDB identity table with an org file.

The table is keyed by the token's ``sub``, never by username: usernames can
be reassigned, and ``sub`` is what the interceptors read from the JWT.
"""

from collections.abc import Mapping, Set
from dataclasses import dataclass

from sentinel_engine.filters import is_valid_tag
from sentinel_engine.principal import SUBJECT_PATTERN


@dataclass(frozen=True)
class SyncPlan:
    put: dict[str, frozenset[str]]
    delete: frozenset[str]


def plan_sync(
    current: Mapping[str, Set[str]], desired: Mapping[str, Set[str]], *, prune: bool = False
) -> SyncPlan:
    """Items to write so the table matches *desired*; optionally delete everyone else."""
    for subject, tags in desired.items():
        if not SUBJECT_PATTERN.fullmatch(subject):
            raise ValueError(f"invalid subject: {subject!r}")
        if not tags or not all(is_valid_tag(t) for t in tags):
            raise ValueError(f"invalid tags for {subject}: {sorted(tags)}")
    put = {
        subject: frozenset(tags)
        for subject, tags in desired.items()
        if frozenset(current.get(subject, ())) != frozenset(tags)
    }
    delete: frozenset[str] = frozenset(set(current) - set(desired)) if prune else frozenset()
    return SyncPlan(put, delete)
