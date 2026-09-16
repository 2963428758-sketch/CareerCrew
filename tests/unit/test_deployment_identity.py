import pytest

from scripts.deployment_identity import deployment_identity


@pytest.mark.parametrize("key", ["PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"])
def test_inherited_routing_is_rejected(monkeypatch, key):
    monkeypatch.setenv(key, "alternate-target")
    with pytest.raises(ValueError, match="routing"):
        deployment_identity("postgresql://u@db.example/app", "https://q.example")


def test_blank_query_routing_is_rejected():
    with pytest.raises(ValueError, match="routing"):
        deployment_identity("postgresql://u@db.example/app?host=", "https://q.example")
