"""Launch the native desktop application."""
import argparse


def main():
    parser=argparse.ArgumentParser(description="ATLAS Watchdog — read-only microscope log monitoring")
    parser.add_argument("--state-dir",help="Isolated writable application state directory")
    parser.add_argument("--demo",action="store_true",help="Use temporary simulated sources; automatic alerts start off")
    parser.add_argument("--smoke-test",action="store_true",help="Open the desktop UI, exercise its worker and exit")
    parser.add_argument("--screenshot",help="Save a window image for local review")
    args=parser.parse_args()
    from .gui import run
    return run(args.state_dir,args.demo,args.smoke_test,args.screenshot)


if __name__=="__main__":
    raise SystemExit(main())
