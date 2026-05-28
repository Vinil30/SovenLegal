import os
import ssl

from dotenv import load_dotenv
from flask import Flask, url_for
from flask_bcrypt import Bcrypt
from pymongo import MongoClient

load_dotenv()

from router import register_routes

FAISS_INDEX_PATH = os.getenv("FAISS_INDEX_PATH", "faiss_index")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey123")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(
    MONGO_URI,
    tls=True,
    tlsCAFile=ssl.get_default_verify_paths().cafile
)
db = client["soven_legal"]

users = db["users"]
documents = db["documents"]
deadlines_col = db["deadlines"]
answers_col = db["find_users"]
lawyers = db["lawyers"]
bcrypt = Bcrypt(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")

ROUTE_CONTEXT = {
    "db": db,
    "users": users,
    "documents": documents,
    "deadlines_col": deadlines_col,
    "answers_col": answers_col,
    "lawyers": lawyers,
    "bcrypt": bcrypt,
    "FAISS_INDEX_PATH": FAISS_INDEX_PATH,
    "GROQ_API_KEY": GROQ_API_KEY,
    "OPENAI_BASE_URL": OPENAI_BASE_URL,
    "OPENAI_MODEL": OPENAI_MODEL,
}

register_routes(app, ROUTE_CONTEXT)

@app.route("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.svg")

@app.after_request
def add_favicon_links(response):
    if response.content_type.startswith("text/html"):
        html = response.get_data(as_text=True)
        if "favicon.svg" not in html and "</head>" in html:
            favicon_url = f'{url_for("static", filename="favicon.svg")}?v=2'
            favicon_links = (
                f'<link rel="icon" type="image/svg+xml" '
                f'href="{favicon_url}">\n'
                f'<link rel="shortcut icon" '
                f'href="{favicon_url}">\n'
            )
            html = html.replace("</head>", f"{favicon_links}</head>", 1)
            response.set_data(html)
            response.headers["Content-Length"] = len(response.get_data())

    return response

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes"}
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=debug, host=host, port=port)
