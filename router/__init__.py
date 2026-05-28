from .auth import register_routes as register_auth
from .documents import register_routes as register_documents
from .dashboard import register_routes as register_dashboard
from .directory import register_routes as register_directory
from .user_chat import register_routes as register_user_chat
from .find_users import register_routes as register_find_users
from .lawyer_auth import register_routes as register_lawyer_auth
from .case_files import register_routes as register_case_files
from .cases import register_routes as register_cases
from .lawyer_chat import register_routes as register_lawyer_chat
from .milestones import register_routes as register_milestones


def register_routes(app, context):
    register_auth(app, context)
    register_documents(app, context)
    register_dashboard(app, context)
    register_directory(app, context)
    register_user_chat(app, context)
    register_find_users(app, context)
    register_lawyer_auth(app, context)
    register_case_files(app, context)
    register_cases(app, context)
    register_lawyer_chat(app, context)
    register_milestones(app, context)
