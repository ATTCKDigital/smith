from flask import Flask

app = Flask(__name__)


@app.route("/")
def index():
    return "hello"


@app.route("/items", methods=["POST"])
def create_item():
    return "ok"


@app.route("/items/<id>", methods=["PUT", "PATCH"])
def update_item(id):
    return "ok"
