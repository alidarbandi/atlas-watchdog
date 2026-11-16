"""Launch the native desktop application."""
import argparse


def main():
    parser=argparse.ArgumentParser(description="ATLAS Watchdog — read-only microscope log monitoring")
    parser.add_argument("--state-dir",help="Isolated writable application state directory")
    parser.add_argument("--demo",action="store_true",help="Use temporary simulated sources; automatic alerts start off")
    parser.add_argument("--smoke-test",action="store_true",help="Open the desktop UI, exercise its worker and exit")
    parser.add_argument("--screenshot",help="Save a window image for local review")
    parser.add_argument("--preflight", action="store_true", help="Report OS/profile without importing Qt")
    args=parser.parse_args()
    from .runtime import preflight, write_startup_report, native_error
    report = {}
    location = "Startup report unavailable (destination may be protected)."
    try:
        report = preflight()
        try:
            location = str(write_startup_report(report))
        except (OSError, ValueError):
            pass
        if args.preflight:
            import json
            print(json.dumps(report, indent=2))
            return int(bool(report["errors"]))
        if report["errors"]:
            raise RuntimeError("OS/profile preflight failed")
        from .gui import run
        return run(args.state_dir,args.demo,args.smoke_test,args.screenshot)
    except Exception as exc:
        try:
            location = str(write_startup_report(report, exc))
        except (OSError, ValueError):
            pass
        message = ("ATLAS Watchdog could not start. " + type(exc).__name__ + "\n"
                   + "\n".join(report.get("errors", [])) + "\n"
                   + "Profile: " + str(report.get("profile", "unknown")) + "; Windows build: "
                   + str(report.get("build", "unknown")) + "\n"
                   + "Expected: " + str(report.get("expected_baseline", "see compatibility guide")) + "\n"
                   + "Diagnostics: " + location + "\nUse the complete diagnostic folder for investigation.")
        native_error(message, console_only=args.smoke_test or args.preflight)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
