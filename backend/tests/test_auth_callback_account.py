import importlib
router = importlib.import_module("app.features.auth.router")

def test_callback_uses_account_returned_by_exchange(monkeypatch):
    seen = {}
    monkeypatch.setattr(router.gmail_auth, "exchange_code", lambda code, state: "selected-account")
    def profile(account):
        seen["account"] = account
        return {"emailAddress": "owner@example.com"}
    monkeypatch.setattr(router, "get_profile", profile)
    monkeypatch.setattr(router, "create_session", lambda account: seen.setdefault("session_account", account) or "session")
    response = router.callback(code="code", state="state", error=None)
    assert seen["account"] == "selected-account"
    assert seen["session_account"] == "selected-account"
    assert response.status_code == 307
