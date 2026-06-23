#!/usr/bin/env python3
# Copyright 2026 sigfridvonshrink
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Prep plan/journal data models — the Fingerprint / Operation / Plan / Journal /
JournalOperationResult dataclasses and their schema constants + cache-freshness counters.
Extracted from photos_1_prep.py, which re-exports them via `from ._prep_models import *`."""

import os
import sys
import json
import hashlib
import tempfile
import subprocess
import select
import socket
import fcntl
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import uuid
import sqlite3
import threading
import contextlib
import ctypes
import errno

# ==============================================================================
# CONFIGURATION BLOCK
# ==============================================================================
from .photos_utils import CONFIG, CAMERA_IDENTITY_FIELDS, folder_name, managed_folder_names, dedup_priority, selected_gpx_root, missing_managed_folders, FOLDER_ROLES
from .reporting import get_reporter
from .photos_utils import (_move_no_clobber, _move_link_unlink, _get_renameat2,
                          WorkspaceCache, WorkspaceLock, ContentHasher,
                          CACHE_SCHEMA_VERSION, FINGERPRINT_ALGORITHM_VERSION,
                          allocate_suffix)


__all__ = [
    'empty_cache_freshness_counts',
    'STATUS_TO_CACHE_FRESHNESS_KEY',
    'PREP_ALLOWED_OPERATION_TYPES',
    'PLAN_SCHEMA_VERSION',
    'Fingerprint',
    'Operation',
    'Plan',
    'JournalOperationResult',
    'Journal',
]

def empty_cache_freshness_counts() -> dict:
    return {
        "total_files": 0,
        "metadata_reused_from_cache": 0,
        "metadata_extracted_ok": 0,
        "metadata_extracted_empty": 0,
        "metadata_extraction_failed": 0,
        "metadata_not_applicable": 0,
        "metadata_missing": 0,
    }

STATUS_TO_CACHE_FRESHNESS_KEY = {
    "reused_from_cache": "metadata_reused_from_cache",
    "extracted_ok": "metadata_extracted_ok",
    "extracted_empty": "metadata_extracted_empty",
    "extraction_failed": "metadata_extraction_failed",
    "not_applicable": "metadata_not_applicable",
}

PREP_ALLOWED_OPERATION_TYPES = {
    "mkdir",
    "move_no_clobber",
    "rename_no_clobber",
    "quarantine_move",
    "db_upsert",
    "db_remove",
}

# Plan serialization/schema version. A plan whose version differs from this is from a
# different tool/schema and is rejected at execute time (prep Section 14.3.2).
PLAN_SCHEMA_VERSION = 1


# ==============================================================================
# SCHEMAS & DATA MODELS

# ==============================================================================

@dataclass
class Fingerprint:
    algorithm: str
    value: str

@dataclass
class Operation:
    operation_id: str
    type: str  # "mkdir" | "move_no_clobber" | "rename_no_clobber" | "quarantine_move" | "db_upsert" | "db_remove"
    reason: str
    source: Optional[str] = None
    destination: Optional[str] = None
    preconditions: Dict[str, Any] = field(default_factory=dict)
    verification: Dict[str, Any] = field(default_factory=dict)
    database_effects_after_verification: List[Dict[str, Any]] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Plan:
    plan_version: int
    plan_id: str
    command: str
    created_at: str
    workspace_root: str
    digikam_root: Optional[str]
    config_fingerprint: Fingerprint
    instruction_fingerprints: Dict[str, Fingerprint] # key: file path (relative to workspace), value: fingerprint
    locks_required: List[str]
    summary: Dict[str, Any]
    blockers: List[str]
    warnings: List[str]
    operations: List[Operation]
    workspace_file_preconditions: List[Dict[str, Any]] = field(default_factory=list)
    metadata_dependencies: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Plan':
        data['config_fingerprint'] = Fingerprint(**data['config_fingerprint'])
        data['instruction_fingerprints'] = {
            k: Fingerprint(**v) for k, v in data.get('instruction_fingerprints', {}).items()
        }
        data['operations'] = [Operation(**op) for op in data.get('operations', [])]
        return cls(**data)

@dataclass
class JournalOperationResult:
    operation_id: str
    status: str # "success" | "skipped" | "failed" | "recovered"
    started_at: str
    finished_at: str
    details: Dict[str, Any]

@dataclass
class Journal:
    journal_version: int
    plan_id: str
    started_at: str
    finished_at: Optional[str] = None
    status: str = "started" # "started" | "success" | "failed_recovered" | "failed_intervention_required" | "aborted_before_mutation"
    snapshots: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    operations: List[JournalOperationResult] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    depends_on: Dict[str, Any] = field(default_factory=dict)  # version/fingerprint stamp (§5)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


# ==============================================================================
# CORE COMPONENTS
# ==============================================================================




