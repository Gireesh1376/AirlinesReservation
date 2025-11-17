from flask import Flask
from extensions import db
from views import app_views

app = Flask(__name__)

# --- Database Configuration ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///airlines.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key'

# Initialize DB
db.init_app(app)

# Register routes
app.register_blueprint(app_views)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
