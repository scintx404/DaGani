"""Zero-dependency test runner (pytest is nicer; this runs anywhere Python 3.10+ does)."""
import importlib.util
import inspect
import pathlib
import sys
import tempfile
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def run(path):
    spec = importlib.util.spec_from_file_location("t", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fails = passed = 0
    for name, fn in vars(mod).items():
        if not name.startswith("test_") or not callable(fn):
            continue
        cases = [None]
        if hasattr(fn, "pytestmark"):
            cases = [a for m in fn.pytestmark if m.name == "parametrize" for a in m.args[1]] or [None]
        params = inspect.signature(fn).parameters
        for case in cases:
            kwargs = {}
            if "tmp_path" in params:
                kwargs["tmp_path"] = pathlib.Path(tempfile.mkdtemp())
            try:
                if case is not None:
                    args = case if isinstance(case, tuple) else (case,)
                    fn(*args, **kwargs)
                else:
                    fn(**kwargs)
                passed += 1
            except Exception:
                fails += 1
                print(f"FAIL {name} {case or ''}")
                traceback.print_exc()
    print(f"{passed} passed, {fails} failed")
    return fails


if __name__ == "__main__":
    files = ["test_gani.py", "test_pipeline.py", "test_server.py"]
    failed = sum(run(ROOT / "tests" / name) for name in files)
    sys.exit(1 if failed else 0)
