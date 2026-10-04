import importlib.util

from scout.config import PROJECT_ROOT


def test_bench_script_runs_at_small_size() -> None:
    spec = importlib.util.spec_from_file_location(
        "bench_knn", PROJECT_ROOT / "scripts/bench_knn.py"
    )
    assert spec is not None and spec.loader is not None
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    timings = bench.run(60, 3)
    assert len(timings) == 4 and all(t > 0 for t in timings)
