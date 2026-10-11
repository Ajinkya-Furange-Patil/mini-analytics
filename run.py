import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    cfg = app.config["APP_CONFIG"]
    # Check PORT, BOTKEEP_PORT, or configured port
    port = int(os.environ.get("PORT", os.environ.get("BOTKEEP_PORT", cfg.PORT)))
    host = os.environ.get("HOST", cfg.HOST)
    print(f"[*] Starting Mini Analytics on {host}:{port}...")
    app.run(host=host, port=port, debug=False)
