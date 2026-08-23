"""服务端显式流取消登记测试。"""

from careercrew_api.sse import (
    cancel_registered_stream,
    register_stream_cancellation,
    unregister_stream_cancellation,
)


def test_registered_stream_can_be_cancelled_and_removed():
    event = register_stream_cancellation("u-cancel", "t-cancel")

    assert cancel_registered_stream("u-cancel", "t-cancel") is True
    assert event.is_set() is True

    unregister_stream_cancellation("u-cancel", "t-cancel", event)
    assert cancel_registered_stream("u-cancel", "t-cancel") is False


def test_old_request_cannot_unregister_newer_request():
    old = register_stream_cancellation("u-replace", "t-replace")
    current = register_stream_cancellation("u-replace", "t-replace")

    assert old.is_set() is True
    unregister_stream_cancellation("u-replace", "t-replace", old)
    assert cancel_registered_stream("u-replace", "t-replace") is True
    assert current.is_set() is True
