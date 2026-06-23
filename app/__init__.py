import logging
import os
from flask import Flask

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", os.urandom(32))

    try:
        from app.db import init_db
        init_db()
        logger.info("Banco de dados inicializado.")
    except Exception:
        logger.exception("Falha ao inicializar banco — app continua sem DB.")

    from app.webhooks import webhooks_bp
    from app.dashboard import dashboard_bp
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(dashboard_bp)

    @app.route("/health")
    def health():
        return {"status": "ok"}, 200

    return app
