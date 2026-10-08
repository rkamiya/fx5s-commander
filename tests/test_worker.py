import queue
import threading

from fx5s_commander.worker import TaskWorker

TIMEOUT = 5.0


def make_worker():
    results = queue.Queue()
    exited = threading.Event()
    worker = TaskWorker(on_done=results.put, on_exit=exited.set)
    worker.start()
    return worker, results, exited


def blocking_task(name, started, release):
    def task():
        started.set()
        release.wait(TIMEOUT)
        return name

    return task


def test_runs_task_and_reports_result():
    worker, results, exited = make_worker()

    assert worker.submit(lambda: "done")
    assert results.get(timeout=TIMEOUT) == "done"

    worker.shutdown(TIMEOUT)
    assert exited.is_set()


def test_exception_is_reported_as_result():
    worker, results, _ = make_worker()

    def boom():
        raise RuntimeError("boom")

    worker.submit(boom)
    assert isinstance(results.get(timeout=TIMEOUT), RuntimeError)
    worker.shutdown(TIMEOUT)


def test_normal_task_rejected_while_busy_but_priority_accepted():
    worker, results, _ = make_worker()
    started, release = threading.Event(), threading.Event()

    assert worker.submit(blocking_task("on", started, release))
    assert started.wait(TIMEOUT)
    assert worker.busy

    assert not worker.submit(lambda: "off")
    assert worker.submit(lambda: "stop", priority=True)
    assert not worker.submit(lambda: "stop2", priority=True)  # 待ちの停止要求は 1 件まで

    release.set()
    assert [results.get(timeout=TIMEOUT) for _ in range(2)] == ["on", "stop"]
    worker.shutdown(TIMEOUT)
    assert not worker.busy


def test_priority_task_runs_before_queued_normal_task():
    results = queue.Queue()
    worker = TaskWorker(on_done=results.put)
    # スレッド開始前に積んでおき、取り出し順だけを確かめる
    assert worker.submit(lambda: "on")
    assert worker.submit(lambda: "stop", priority=True)
    worker.start()

    assert [results.get(timeout=TIMEOUT) for _ in range(2)] == ["stop", "on"]
    worker.shutdown(TIMEOUT)


def test_shutdown_finishes_accepted_tasks_and_rejects_new_ones():
    worker, results, exited = make_worker()
    started, release = threading.Event(), threading.Event()
    worker.submit(blocking_task("on", started, release))
    assert started.wait(TIMEOUT)
    worker.submit(lambda: "stop", priority=True)

    release.set()
    worker.shutdown(TIMEOUT)

    assert exited.is_set()
    assert [results.get_nowait() for _ in range(2)] == ["on", "stop"]
    assert not worker.submit(lambda: "late", priority=True)
