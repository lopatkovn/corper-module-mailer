"""Backend for the 'mailer' module.

Auth: nginx adds X-Employee-Id header after auth_request /_auth/verify.
      corper-shared.ProxyEmployee builds a user object from that header.

DB:   DATABASE_URL is injected by deploy-agent from core.module_secret.

Multi-company / permissions:
    Don't trust `current_user.company_id` for filtering — it's the user's
    *default* company, not the one selected in the shell. Use
    `corper_shared.context.active_company_id(current_user, request)` instead.
    Shell always sends `?company_id=N` for the currently selected company.
"""
import os
from flask import Flask, jsonify, request, abort
from flask_login import LoginManager, login_required, current_user
from flask_sqlalchemy import SQLAlchemy

from corper_shared.auth import make_user_loader, make_request_loader, ProxyEmployee
from corper_shared.service_client import CoreClient
from corper_shared.context import active_company_id, require_section

MODULE_NAME = os.environ.get("MODULE_NAME", "mailer")
SECTION = "notifications"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

core = CoreClient(os.environ.get("CORE_REGISTRY_URL", "http://core-registry:5001"))

login_manager = LoginManager(app)
# user_loader — session-based вход (dev-консоль / standalone).
# request_loader — ОБЯЗАТЕЛЬНО для портала: модуль в iframe stateless,
# nginx auth_request кладёт личность в заголовок X-Employee-Id, и читает
# его только request_loader. Без него все @login_required → 401 на портале.
login_manager.user_loader(make_user_loader(core))
login_manager.request_loader(make_request_loader(core, app.config["SECRET_KEY"]))


from models import DemoItem  # noqa: E402


@app.get("/health")
def health():
    return {"ok": True, "module": MODULE_NAME}


# Example: rich department context (manager, ancestors, descendants, subtree employees).
# Single endpoint, pull-only — see INTEGRATION.md → /api/companies/{cid}/departments/{did}/full
#
#   info = core.get_department_full(company_id, dept_id, include_subtree_employees=True)
#   emails = [e["email"] for e in info.get("subtree_employees", []) if e["email"]]
#   manager = info.get("manager")
#   for child in info.get("descendants", []):
#       print(child["name"], child["direct_employee_count"])


@app.get("/items")
@login_required
def list_items():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "view")
    items = DemoItem.query.filter_by(company_id=company_id).all()
    return jsonify([{
        "id": i.id, "title": i.title, "created_at": i.created_at.isoformat() if i.created_at else None,
    } for i in items])


@app.post("/items")
@login_required
def create_item():
    company_id = active_company_id(current_user, request)
    require_section(current_user, company_id, SECTION, core, "manage")
    data = request.get_json(force=True) or {}
    if not data.get("title"):
        return jsonify({"error": "title required"}), 400
    item = DemoItem(
        company_id=company_id,
        title=data["title"],
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({"id": item.id}), 201


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
