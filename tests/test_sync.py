"""Exercise synchronous ownership, real pipes, thread shutdown and API parity."""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import sys
import threading
from pathlib import Path
from typing import get_type_hints

import pytest

from pi_coding_agent_client.client import IN_SYNC_UI, AsyncPiClient
from pi_coding_agent_client.errors import (
    PiCommandError,
    PiProcessError,
    PiTimeoutError,
    PiUIHandlerError,
)
from pi_coding_agent_client.sync import PiClient
from pi_coding_agent_client.types import Limits

FAKE = str(Path(__file__).with_name("fake_sync_pi.py"))


def client(**options):
    return PiClient(
        executable=[sys.executable, FAKE], limits=Limits(cleanup_timeout=0.2), **options
    )


def test_construction_is_idle_and_prestart_call_does_not_leak_a_coroutine():
    pi = client()
    assert pi._thread is None
    assert not pi.running
    with pytest.raises(PiProcessError):
        pi.get_state()
    pi.close()
    pi.close()
    with pytest.raises(PiProcessError):
        pi.start()


def test_persistent_loop_properties_and_clean_join():
    pi = client()
    with pi:
        loop_thread = pi._thread
        assert loop_thread is not None and loop_thread.is_alive()
        assert pi.running
        assert pi.pi_version == "0.85.1"
        assert pi.compatibility == "tested"
        assert pi.session.session_id == "synthetic-session"
        assert pi.run("hello").text == "hello"
        pi.set_session_name("renamed")
        assert pi.session.session_name == "renamed"
        assert pi.run("again").text == "again"
        assert pi._thread is loop_thread
        assert not pi.busy
        assert pi.stderr_tail == ""
    assert not pi.running
    assert not loop_thread.is_alive()
    assert pi._loop.is_closed()
    pi.close()


def test_startup_failure_stops_and_joins_thread():
    pi = PiClient(executable="pi-this-executable-does-not-exist")
    with pytest.raises(PiProcessError):
        pi.start()
    assert pi._thread is not None and not pi._thread.is_alive()
    assert pi._loop.is_closed()
    pi.close()


def test_raw_errors_and_response_timeout_keep_async_semantics():
    with client() as pi:
        with pytest.raises(PiCommandError) as caught:
            pi.request("fail")
        assert caught.value.error == "synthetic rejection"
        with pytest.raises(PiTimeoutError) as caught:
            pi.request("silent", timeout=0.05)
        assert caught.value.uncertain
        assert pi.get_state()["sessionId"] == "synthetic-session"
        assert pi.request("capture", empty="", enabled=False)["data"] == {
            "empty": "",
            "enabled": False,
        }


def test_stream_iteration_cached_result_and_future_events():
    with client() as pi:
        with pi.events() as events:
            with pi.stream("streamed") as stream:
                observed = list(stream)
                assert [event.text_delta for event in observed if event.text_delta] == ["streamed"]
                first = stream.result()
                assert first.text == "streamed"
                assert stream.result() is first
            assert next(events).type == "agent_start"
        with pi.events() as events:
            events.close()
            with pytest.raises(StopIteration):
                next(events)


def test_early_stream_exit_cleans_owned_run_and_client_can_run_again():
    with client() as pi:
        with pi.stream("hold") as stream:
            assert next(stream).type == "agent_start"
            assert pi.busy
        assert not pi.busy
        assert not pi.get_state()["isStreaming"]
        assert pi.run("after abort").text == "after abort"


def test_closed_contexts_are_single_use_even_before_entry():
    with client() as pi:
        for context in (pi.events(), pi.stream("never sent")):
            context.close()
            with pytest.raises(RuntimeError, match="single-use"):
                context.__enter__()
        assert not pi.busy


def test_concurrent_abort_unblocks_run_and_concurrent_close_joins_once():
    pi = client()
    pi.start()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        with pi.events() as events:
            running = executor.submit(pi.run, "hold")
            assert next(events).type == "agent_start"
            executor.submit(pi.abort).result(timeout=3)
            assert running.result(timeout=3).text == ""
        closes = [executor.submit(pi.close) for _ in range(3)]
        for closing in closes:
            closing.result(timeout=3)
    assert not pi._thread.is_alive()


def test_close_wakes_blocked_run_and_subscription_readers():
    pi = client()
    pi.start()
    events = pi.events().__enter__()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        run = executor.submit(pi.run, "hold")
        assert next(events).type == "agent_start"
        reading = executor.submit(next, events)
        pi.close()
        with pytest.raises(PiProcessError):
            run.result(timeout=3)
        with pytest.raises(PiProcessError):
            reading.result(timeout=3)
    events.close()
    assert not pi._thread.is_alive()


def test_ui_callback_runs_outside_loop_and_round_trips():
    callback_threads = []

    def handle(request):
        callback_threads.append(threading.current_thread())
        return False

    with client(ui_handler=handle) as pi:
        with pi.events() as events:
            assert pi.prompt("/confirm")["success"]
            assert next(events).type == "extension_ui_request"
            assert next(events).raw["reply"]["confirmed"] is False
        assert callback_threads and callback_threads[0] is not pi._thread


def test_ui_reentrancy_fails_without_deadlocking_and_sends_cancellation():
    def handle(request):
        return pi.get_state()

    with client(ui_handler=handle) as pi:
        with pytest.raises(PiUIHandlerError) as caught:
            pi.prompt("/confirm")
        assert isinstance(caught.value.__cause__, RuntimeError)


def test_reentrancy_guard_also_covers_loop_thread():
    with client() as pi:

        async def call_from_loop():
            with pytest.raises(RuntimeError, match="callbacks"):
                pi.get_state()

        pi._call(call_from_loop)
        token = IN_SYNC_UI.set(True)
        try:
            with pytest.raises(RuntimeError, match="callbacks"):
                pi.close()
        finally:
            IN_SYNC_UI.reset(token)


def test_keyboard_interrupt_waits_for_actual_async_cleanup(monkeypatch):
    entered = threading.Event()
    cleaned = threading.Event()

    async def operation():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.05)
            cleaned.set()

    with client() as pi:
        original_result = concurrent.futures.Future.result
        interrupted = False

        def interrupt_once(future, timeout=None):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                assert entered.wait(3)
                raise KeyboardInterrupt
            return original_result(future, timeout)

        with monkeypatch.context() as patch:
            patch.setattr(concurrent.futures.Future, "result", interrupt_once)
            with pytest.raises(KeyboardInterrupt):
                pi._call(operation)
        assert cleaned.is_set()
        assert pi.run("still usable").text == "still usable"


def test_keyboard_interrupt_run_clears_and_aborts_before_return(monkeypatch):
    with client() as pi:
        with pi.events() as events:
            original_result = concurrent.futures.Future.result
            interrupted = False

            def interrupt_once(future, timeout=None):
                nonlocal interrupted
                if not interrupted:
                    interrupted = True
                    # Consume from another thread to observe real prompt acceptance.
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        observed = executor.submit(next, events)
                        assert original_result(observed, 3).type == "agent_start"
                    raise KeyboardInterrupt
                return original_result(future, timeout)

            with monkeypatch.context() as patch:
                patch.setattr(concurrent.futures.Future, "result", interrupt_once)
                with pytest.raises(KeyboardInterrupt):
                    pi.run("hold")
        assert not pi.busy
        assert not pi.get_state()["isStreaming"]


def test_keyboard_interrupt_during_close_finishes_shutdown(monkeypatch):
    pi = client()
    pi.start()
    entered = threading.Event()
    reaped = threading.Event()
    original_close = pi._client.aclose

    async def delayed_close():
        entered.set()
        await asyncio.sleep(0.05)
        await original_close()
        reaped.set()

    monkeypatch.setattr(pi._client, "aclose", delayed_close)

    def interrupt(future, timeout=None):
        assert entered.wait(3)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(concurrent.futures.Future, "result", interrupt)
        with pytest.raises(KeyboardInterrupt):
            pi.close()
    assert reaped.is_set()
    assert pi._thread_done.is_set()
    assert not pi._thread.is_alive()


def test_close_does_not_wait_for_a_blocked_user_callback():
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def handle(request):
        entered.set()
        try:
            release.wait(5)
        finally:
            completed.set()

    pi = client(ui_handler=handle)
    pi.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            prompt = executor.submit(pi.prompt, "/confirm")
            assert entered.wait(3)
            pi.close()
            assert not pi._thread.is_alive()
            assert not completed.is_set()
            with pytest.raises(PiProcessError):
                prompt.result(timeout=3)
    finally:
        release.set()
        assert completed.wait(3)
        pi.close()


def test_explicit_methods_preserve_async_signatures_and_forward_all_arguments(monkeypatch):
    public = {
        name
        for name, value in vars(AsyncPiClient).items()
        if inspect.iscoroutinefunction(value) and not name.startswith("_")
    } - {"start", "aclose"}
    assert len(public) == 35  # 33 commands plus raw request and run.
    assert inspect.signature(PiClient.__init__) == inspect.signature(AsyncPiClient.__init__)
    seen = []
    marker = object()

    def replacement(name):
        async def record(*args, **kwargs):
            seen.append((name, args, kwargs, threading.current_thread()))
            return marker

        return record

    with client() as pi:
        for name in sorted(public):
            async_method = getattr(AsyncPiClient, name)
            sync_method = getattr(PiClient, name)
            assert inspect.signature(sync_method) == inspect.signature(async_method), name
            assert get_type_hints(sync_method) == get_type_hints(async_method), name
            monkeypatch.setattr(pi._client, name, replacement(name))
            signature = inspect.signature(sync_method)
            args = []
            kwargs = {}
            for parameter in list(signature.parameters.values())[1:]:
                if parameter.kind is inspect.Parameter.VAR_KEYWORD:
                    kwargs["future_field"] = False
                elif parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD:
                    args.append(f"synthetic-{parameter.name}")
                elif parameter.kind is inspect.Parameter.KEYWORD_ONLY:
                    kwargs[parameter.name] = parameter.default
            result = getattr(pi, name)(*args, **kwargs)
            assert result is (
                None if get_type_hints(sync_method)["return"] is type(None) else marker
            )
            called_name, called_args, called_kwargs, thread = seen[-1]
            assert (called_name, called_args, called_kwargs) == (name, tuple(args), kwargs)
            assert thread is pi._thread
