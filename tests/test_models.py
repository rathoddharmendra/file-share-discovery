"""Tests for model construction and serialization."""

from isilon_discovery.models import ShareRecord, QuotaRecord, SecurityGroupRecord


def test_share_from_smb_api():
    raw = {
        "name": "Finance",
        "path": "/ifs/data/finance",
        "description": "Finance team share",
        "browsable": True,
        "dfs_target": True,
        "acl": [],
    }
    share = ShareRecord.from_smb_api(node_id=1, zone="Finance", raw=raw)
    assert share.name == "Finance"
    assert share.share_type == "smb"
    assert share.path == "/ifs/data/finance"
    assert share.is_dfs_target is True
    assert share.dfs_pseudo_path is None  # ps_managed — must be None from Python
    assert share.data_type is None  # user_managed — must be None from Python


def test_share_db_dict_excludes_id():
    share = ShareRecord(node_id=1, name="test", share_type="smb", path="/ifs/test")
    d = share.to_db_dict()
    assert "id" not in d
    assert "node_id" in d


def test_quota_from_api():
    raw = {
        "type": "directory",
        "path": "/ifs/data/finance",
        "thresholds": {"hard": 10_737_418_240, "soft": 9_663_676_416},
        "usage": {"fslogical": 5_368_709_120, "inodes": 12345},
    }
    quota = QuotaRecord.from_api(share_id=1, raw=raw)
    assert quota.hard_limit_gb == 10.0
    assert quota.usage_gb == 5.0
    assert quota.enforced is True


def test_security_group_round_trip():
    group = SecurityGroupRecord(group_name="CORP\\Finance-RW", group_sid="S-1-5-21-123-456")
    d = group.to_db_dict()
    assert d["group_name"] == "CORP\\Finance-RW"
    assert "id" not in d

