"""Start the PM Planner:  python run.py   (add --reset to rebuild the demo data)"""
import argparse
import threading
import webbrowser

from pmplanner.server import app, bootstrap_data

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete the local planning DB and regenerate mock data")
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    bootstrap_data(reset=a.reset)
    url = f"http://127.0.0.1:{a.port}"
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"PM Planner running at {url}  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=a.port, debug=False)
