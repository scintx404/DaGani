"""Zero-dependency test runner."""
import importlib.util,inspect,pathlib,sys,tempfile,traceback
ROOT=pathlib.Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
def run(path):
 spec=importlib.util.spec_from_file_location("t",path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);fails=passed=0
 for name,fn in vars(mod).items():
  if not name.startswith("test_") or not callable(fn):continue
  try:fn(**({"tmp_path":pathlib.Path(tempfile.mkdtemp())} if "tmp_path" in inspect.signature(fn).parameters else {}));passed+=1
  except Exception:fails+=1;print(f"FAIL {name}");traceback.print_exc()
 print(f"{passed} passed, {fails} failed");return fails
if __name__=="__main__":sys.exit(sum(run(ROOT/"tests"/name) for name in ("test_gani.py","test_pipeline.py","test_copilot.py")))
