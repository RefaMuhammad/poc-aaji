from mab_pipeline.tasks import ping


def test_ping_job():
    assert ping() == "pong"
