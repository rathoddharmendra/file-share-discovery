"""Tests for snapshot write/read/diff logic."""

import tempfile

import pytest

from isilon_discovery.snapshot import SnapshotManager, ShareIdentity


@pytest.fixture
def tmp_snapshot_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _make_shares(names):
    return {ShareIdentity(name=n, share_type="smb", access_zone="System") for n in names}


def test_write_and_load(tmp_snapshot_dir):
    mgr = SnapshotManager(tmp_snapshot_dir)
    shares = _make_shares(["Finance", "HR", "IT"])
    mgr.write("node-1", list(shares))
    loaded = mgr.load_latest("node-1")
    assert loaded == shares


def test_diff_detects_additions(tmp_snapshot_dir):
    mgr = SnapshotManager(tmp_snapshot_dir)
    prev = _make_shares(["Finance", "HR"])
    curr = _make_shares(["Finance", "HR", "NewShare"])
    added, removed = mgr.diff(prev, curr)
    assert ShareIdentity("NewShare", "smb", "System") in added
    assert not removed


def test_diff_detects_removals(tmp_snapshot_dir):
    mgr = SnapshotManager(tmp_snapshot_dir)
    prev = _make_shares(["Finance", "HR", "OldShare"])
    curr = _make_shares(["Finance", "HR"])
    added, removed = mgr.diff(prev, curr)
    assert ShareIdentity("OldShare", "smb", "System") in removed
    assert not added


def test_diff_first_run_returns_all_as_added(tmp_snapshot_dir):
    mgr = SnapshotManager(tmp_snapshot_dir)
    curr = _make_shares(["Finance", "HR"])
    added, removed = mgr.diff(None, curr)
    assert added == curr
    assert not removed


def test_no_snapshot_returns_none(tmp_snapshot_dir):
    mgr = SnapshotManager(tmp_snapshot_dir)
    assert mgr.load_latest("nonexistent-node") is None

