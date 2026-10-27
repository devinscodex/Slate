import settings


def test_single_instance_defaults_true():
    assert settings.load()["single_instance"] is True


def test_single_instance_round_trips_false():
    settings.save({"single_instance": False})
    assert settings.load()["single_instance"] is False


def test_single_instance_round_trips_true_after_false():
    settings.save({"single_instance": False})
    settings.save({"single_instance": True})
    assert settings.load()["single_instance"] is True
