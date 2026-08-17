from devscope_bridge.whatsapp import cockpit_config


def test_defaults_and_roundtrip(tmp_path):
    p = tmp_path / "cfg.json"
    cfg = cockpit_config.load(p)
    assert cfg["threshold_hours"] == 3
    assert cfg["dm_in_scope"] is True
    assert cfg["group_allowlist"] == []
    cfg["threshold_hours"] = 6
    cfg["group_allowlist"].append("g1@g.us")
    cockpit_config.save(p, cfg)
    assert cockpit_config.load(p)["threshold_hours"] == 6
    assert cockpit_config.load(p)["group_allowlist"] == ["g1@g.us"]


def test_in_scope_logic():
    cfg = {"dm_in_scope": True, "group_allowlist": ["g1@g.us"],
           "blacklist": ["bad@g.us"], "threshold_hours": 3}
    assert cockpit_config.is_in_scope(cfg, "5@c.us", is_group=False) is True
    assert cockpit_config.is_in_scope(cfg, "g1@g.us", is_group=True) is True
    assert cockpit_config.is_in_scope(cfg, "g2@g.us", is_group=True) is False
    assert cockpit_config.is_in_scope(cfg, "bad@g.us", is_group=True) is False


def test_dm_out_of_scope_when_disabled():
    cfg = {"dm_in_scope": False, "group_allowlist": [], "blacklist": []}
    assert cockpit_config.is_in_scope(cfg, "5@c.us", is_group=False) is False
