import os
from flask import Flask, send_from_directory
from app.config import Config
from app.db import init_db, close_db
from app.routes_collect import collect_bp
from app.routes_api import api_bp
from app.routes_admin import admin_bp


def create_app(test_config=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Load configuration
    cfg = Config()
    app.config["APP_CONFIG"] = cfg
    app.config["SECRET_KEY"] = cfg.SECRET_KEY
    app.config["DB_PATH"] = cfg.DB_PATH
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if cfg.COOKIE_SECURE:
        app.config["SESSION_COOKIE_SECURE"] = True

    # Override for tests if provided
    if test_config:
        app.config.update(test_config)
        for k, v in test_config.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

    # Initialize SQLite database & migrations
    init_db(app.config["DB_PATH"])

    # Teardown database connections cleanly
    app.teardown_appcontext(close_db)

    # Register blueprints
    app.register_blueprint(collect_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    # Route for tracker script
    @app.route("/tracker.js")
    def serve_tracker():
        return send_from_directory(
            os.path.join(app.root_path, "static"),
            "tracker.js",
            mimetype="application/javascript",
        )

    # Security Headers Hook
    @app.after_request
    def apply_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Content Security Policy allowing local styles, fonts, and scripts
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:;"
        )
        return response

    return app
