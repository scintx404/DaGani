import argparse,asyncio,logging
from .server import build_router,serve
def main():
    p=argparse.ArgumentParser(prog="gani-agent");p.add_argument("--port",type=int,default=8765);p.add_argument("--host",default="127.0.0.1");p.add_argument("-v",action="store_true");a=p.parse_args();logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO);asyncio.run(serve(build_router(),a.host,a.port))
if __name__=="__main__":main()
