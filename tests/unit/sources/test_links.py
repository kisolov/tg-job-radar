import pytest

from radar.sources.links import extract_chat_links, normalize_username


@pytest.mark.parametrize("raw,exp", [
    ("@Freelance_IT", "freelance_it"),
    ("https://t.me/s/jobs_py", "jobs_py"),
    ("t.me/+AbC", "+AbC"),
    ("http://example.com", None),
    ("https://t.me/joinchat/AAAAAEx1", "+AAAAAEx1"),
    ("https://telegram.me/Python_Jobs/1234", "python_jobs"),
    ("jobs_py", "jobs_py"),
    ("@some_helper_bot", None),
    ("@ab", None),
    ("t.me/addstickers/foo", None),
])
def test_normalize_username(raw, exp):
    assert normalize_username(raw) == exp


def test_extract_chat_links():
    text = (
        "Ещё вакансии: t.me/devjobs, https://t.me/+InViTe123 и https://t.me/s/remote_it/55. "
        "Резюме на hr@company.ru, вопросы @hr_anna"
    )
    assert extract_chat_links(text) == ["devjobs", "+InViTe123", "remote_it"]


def test_extract_dedups():
    assert extract_chat_links("t.me/a_chat t.me/A_Chat") == ["a_chat"]
