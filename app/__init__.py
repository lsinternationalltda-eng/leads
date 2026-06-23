import os
from flask import Flask

from app.db import init_db
from app.webhooks import webhooks_bp
from app.dashboard import dashboard_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", os.urandom(32))

    init_db()

    app.register_blueprint(webhooks_bp)
    app.register_blueprint(dashboard_bp)

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app
