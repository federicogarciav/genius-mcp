from app import mcp


def test_server_is_not_none():
    assert mcp is not None


def test_server_has_name():
    assert mcp.name and len(mcp.name) > 0
