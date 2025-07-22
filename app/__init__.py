from flask import Flask
from app.extensions import db, login_manager, migrate

def create_app():
    app = Flask(__name__, template_folder="templates")
    app.config.from_object('config.Config')
    
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.routes.auth import auth
    app.register_blueprint(auth)

    from app.routes.auth import main
    app.register_blueprint(main)

    from app.routes.jobs import jobs
    app.register_blueprint(jobs)

    return app