from radar.panel.auth import PanelAuth, secret_from
from radar.shared.clock import FakeClock


def make(clock: FakeClock) -> PanelAuth:
    return PanelAuth(b"k" * 32, clock, login_ttl_s=600, session_ttl_s=3600)


def test_login_link_redeems_once_into_session():
    clock = FakeClock()
    auth = make(clock)
    token = auth.issue_login()
    session = auth.redeem_login(token)
    assert session and auth.check_session(session)
    assert auth.redeem_login(token) is None  # одноразовая


def test_login_link_expires():
    clock = FakeClock()
    auth = make(clock)
    token = auth.issue_login()
    clock.advance(601)
    assert auth.redeem_login(token) is None


def test_session_expires_and_rejects_tampering():
    clock = FakeClock()
    auth = make(clock)
    session = auth.redeem_login(auth.issue_login())
    assert not auth.check_session(session[:-2] + "xx")
    assert not auth.check_session("garbage")
    assert not auth.check_session("")
    clock.advance(3601)
    assert not auth.check_session(session)


def test_login_token_is_not_a_session_and_other_secret_rejects():
    clock = FakeClock()
    auth = make(clock)
    token = auth.issue_login()
    assert not auth.check_session(token)
    other = PanelAuth(b"z" * 32, clock)
    assert not other.check_session(auth.redeem_login(token))


def test_secret_falls_back_to_bot_token():
    assert secret_from("", "42:TOKEN") == secret_from("", "42:TOKEN")
    assert secret_from("", "42:TOKEN") != secret_from("", "43:TOKEN")
    assert secret_from("explicit", "42:TOKEN") == b"explicit"
