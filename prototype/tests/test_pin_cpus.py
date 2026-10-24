"""pin_cpus.py: a cpuset plan for any host size that keeps Red off the gateway's cores, and no plan when that is impossible."""
import pin_cpus


def cpus(spec):
    out = set()
    for part in spec.split(","):
        first, _, last = part.partition("-")
        out |= set(range(int(first), int(last or first) + 1))
    return out


def test_red_and_the_gateway_never_share_a_core_when_a_plan_exists():
    for n in (4, 5, 6, 8, 12, 32):
        layout = pin_cpus.plan(n)
        assert layout, n
        assert not cpus(layout["red-client"]) & cpus(layout["gateway"]), n
        assert all(max(cpus(spec)) < max(n, 8) for spec in layout.values())
        if n < 8:
            assert all(max(cpus(spec)) < n for spec in layout.values()), n  # never names a core that the host does not have


def test_eight_cpus_match_the_fixed_overlay_and_small_hosts_get_no_pinning():
    assert pin_cpus.plan(8)["gateway"] == "2-3" and pin_cpus.plan(8)["audit-collector"] == "7"
    assert pin_cpus.plan(3) == {} and pin_cpus.plan(1) == {}


def test_generated_overlay_text(tmp_path, monkeypatch):
    monkeypatch.setattr(pin_cpus, "OVERLAY", tmp_path / "overlay.yml")
    pin_cpus.write(4)
    text = (tmp_path / "overlay.yml").read_text()
    assert 'cpuset: "0"' in text and 'cpuset: "1"' in text and 'cpuset: "2-3"' in text
    pin_cpus.write(2)
    assert (tmp_path / "overlay.yml").read_text().splitlines()[-1] == "services: {}"
