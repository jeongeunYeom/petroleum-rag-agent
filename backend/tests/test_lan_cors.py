from app.main import cors_origins


def test_lan_origin_is_opt_in(monkeypatch):
    monkeypatch.delenv("PETROLEUM_LAN_TEST_ORIGIN", raising=False)
    assert cors_origins() == ["http://localhost:3000", "http://127.0.0.1:3000"]

    monkeypatch.setenv("PETROLEUM_LAN_TEST_ORIGIN", "http://10.11.51.110:3000")
    assert cors_origins() == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://10.11.51.110:3000",
    ]
