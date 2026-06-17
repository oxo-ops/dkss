from flask import Flask, render_template, request, redirect, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import json

from flask_sqlalchemy import SQLAlchemy
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///dkss.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    company_name = db.Column(
        db.String(100),
        nullable=False
    )

    vehicle_limit = db.Column(
        db.Integer,
        default=0
    )

    active = db.Column(
        db.Boolean,
        default=True
    )


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    username = db.Column(
        db.String(50),
        nullable=False
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )

    name = db.Column(
        db.String(100),
        nullable=False
    )

    role = db.Column(
        db.String(20),
        default="user"
    )

    office = db.Column(
        db.String(100)
    )

    favorite_vehicles_json = db.Column(
        db.Text,
        default="[]"
    )
class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    vehicle_id = db.Column(db.String(50), nullable=False)

    plate_area = db.Column(db.String(50))
    plate_class = db.Column(db.String(50))
    plate_kana = db.Column(db.String(10))
    plate_number = db.Column(db.String(50))

    type = db.Column(db.String(100))
    office = db.Column(db.String(100))
    inspection_expiry = db.Column(db.String(20))

    deleted = db.Column(
        db.Boolean,
        default=False
    )

class VehicleType(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)

class LicenseType(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)

class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    employee_id = db.Column(db.String(50), nullable=False)

    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50))
    office = db.Column(db.String(100))
    safe_start_date = db.Column(db.String(20))

    vehicles_json = db.Column(db.Text, default="[]")
    licenses_json = db.Column(db.Text, default="[]")

class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    files_json = db.Column(db.Text, default="[]")

    target_type = db.Column(db.String(50))
    target_value = db.Column(db.String(100))

    created_at = db.Column(db.String(20))


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    target_user = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    link = db.Column(db.String(200))
    files_json = db.Column(db.Text, default="[]")

    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.String(20))

class Office(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)

class DeliveryPlace(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)

class Manual(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100))
    filename = db.Column(db.String(200))

class VehiclePatrol(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)

    vehicle_id = db.Column(db.String(50))
    occurred_date = db.Column(db.String(20))
    category = db.Column(db.String(100))
    priority = db.Column(db.String(50))
    content = db.Column(db.Text)

    cause = db.Column(db.Text)
    temporary_action = db.Column(db.Text)
    repair_content = db.Column(db.Text)

    status = db.Column(db.String(50), default="未対応")

    repair_date = db.Column(db.String(20))
    repair_person = db.Column(db.String(100))
    repair_time = db.Column(db.String(50))
    parts = db.Column(db.Text)
    cost = db.Column(db.String(50))

class Checklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(db.String(50), nullable=False)

    name = db.Column(db.String(200), nullable=False)
    target = db.Column(db.String(100))

    frequency_value = db.Column(db.String(20))
    frequency_unit = db.Column(db.String(20))
    display_type = db.Column(db.String(20))

    items_json = db.Column(db.Text, default="[]")

class ChecklistResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    checklist_id = db.Column(
        db.Integer,
        nullable=False
    )

    target_type = db.Column(db.String(50))
    target_user = db.Column(db.String(100))
    target_vehicle = db.Column(db.String(100))
    target_office = db.Column(db.String(100))

    checked_by = db.Column(db.String(100))
    checked_date = db.Column(db.String(30))

    status = db.Column(db.String(30))

    approved_by = db.Column(db.String(100))
    approved_date = db.Column(db.String(30))
    reject_reason = db.Column(db.Text)

    answers_json = db.Column(
        db.Text,
        default="[]"
    )

class VehicleChecklistResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    checklist_id = db.Column(
        db.Integer,
        nullable=False
    )

    vehicle_id = db.Column(
        db.String(50)
    )

    year = db.Column(db.String(10))
    month = db.Column(db.String(10))
    day = db.Column(db.String(10))

    checked_by = db.Column(db.String(100))
    checked_date = db.Column(db.String(30))

    status = db.Column(db.String(30))

    approved_by = db.Column(db.String(100))
    approved_date = db.Column(db.String(30))

    reject_reason = db.Column(db.Text)

    answers_json = db.Column(
        db.Text,
        default="[]"
    )

class PatrolResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    company_code = db.Column(
        db.String(50),
        nullable=False
    )

    created_by_username = db.Column(
        db.String(100)
    )

    created_by_name = db.Column(
        db.String(100)
    )

    date = db.Column(
        db.String(20)
    )

    office = db.Column(
        db.String(100)
    )

    delivery_place = db.Column(
        db.String(100)
    )

    category = db.Column(
        db.String(50)
    )

    content_type = db.Column(
        db.String(50)
    )

    target_type = db.Column(
        db.String(50)
    )

    target_user = db.Column(
        db.String(100)
    )

    content = db.Column(
        db.Text
    )

    files_json = db.Column(
        db.Text,
        default="[]"
    )

    countermeasure = db.Column(
        db.Text
    )

    countermeasure_by = db.Column(
        db.String(100)
    )

    approval_status = db.Column(
        db.String(30)
    )

    reject_reason = db.Column(
        db.Text
    )

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

PATROL_VIEW_TYPES = {"user", "delivery_place"}

@app.before_request
def require_login():
    if request.endpoint in {"login", "register", "static"} or request.endpoint is None:
        return None

    if not session.get("username"):
        return redirect("/login")

    return None


def require_itc():
    return session.get("role") == "itc"

def get_company(company_code):
    return Company.query.filter_by(
        company_code=company_code
    ).first()


def offices_for_current_company():
    query = Office.query

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    return [
        {
            "id": office.id,
            "index": office.id,
            "company_code": office.company_code,
            "name": office.name
        }
        for office in query.all()
    ]

def delivery_places_for_current_company():
    query = DeliveryPlace.query

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    return [
        {
            "id": place.id,
            "index": place.id,
            "company_code": place.company_code,
            "name": place.name
        }
        for place in query.all()
    ]

def manuals_for_current_company():
    query = Manual.query

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    return [
        {
            "id": manual.id,
            "index": manual.id,
            "company_code": manual.company_code,
            "title": manual.title,
            "category": manual.category,
            "filename": manual.filename,
        }
        for manual in query.all()
    ]

def vehicle_patrol_to_dict(patrol):
    return {
        "id": patrol.id,
        "index": patrol.id,
        "company_code": patrol.company_code,
        "vehicle_id": patrol.vehicle_id,
        "occurred_date": patrol.occurred_date,
        "category": patrol.category,
        "priority": patrol.priority,
        "content": patrol.content,
        "cause": patrol.cause,
        "temporary_action": patrol.temporary_action,
        "repair_content": patrol.repair_content,
        "status": patrol.status,
        "repair_date": patrol.repair_date,
        "repair_person": patrol.repair_person,
        "repair_time": patrol.repair_time,
        "parts": patrol.parts,
        "cost": patrol.cost,
    }


def vehicle_patrols_for_current_company():
    query = VehiclePatrol.query

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    return [
        vehicle_patrol_to_dict(patrol)
        for patrol in query.order_by(VehiclePatrol.id.desc()).all()
    ]

def checklist_to_dict(checklist):
    return {
        "id": checklist.id,
        "index": checklist.id,
        "company_code": checklist.company_code,
        "name": checklist.name,
        "target": checklist.target,
        "frequency_value": checklist.frequency_value,
        "frequency_unit": checklist.frequency_unit,
        "display_type": checklist.display_type,
        "items": json.loads(checklist.items_json or "[]"),
    }


def checklists_for_current_company():
    query = Checklist.query

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    return [
        checklist_to_dict(checklist)
        for checklist in query.all()
    ]

def checklist_result_to_dict(result):
    return {
        "id": result.id,
        "index": result.id,
        "company_code": result.company_code,
        "checklist_id": result.checklist_id,
        "target_type": result.target_type,
        "target_user": result.target_user,
        "target_vehicle": result.target_vehicle,
        "target_office": result.target_office,
        "checked_by": result.checked_by,
        "checked_date": result.checked_date,
        "status": result.status,
        "approved_by": result.approved_by,
        "approved_date": result.approved_date,
        "reject_reason": result.reject_reason,
        "answers": json.loads(result.answers_json or "[]"),
    }

def vehicle_checklist_result_to_dict(result):
    return {
        "id": result.id,
        "index": result.id,
        "company_code": result.company_code,
        "checklist_id": result.checklist_id,
        "vehicle_id": result.vehicle_id,
        "year": result.year,
        "month": result.month,
        "day": result.day,
        "checked_by": result.checked_by,
        "checked_date": result.checked_date,
        "status": result.status,
        "approved_by": result.approved_by,
        "approved_date": result.approved_date,
        "reject_reason": result.reject_reason,
        "answers": json.loads(result.answers_json or "[]"),
    }

def patrol_result_to_dict(result):
    return {
        "id": result.id,
        "index": result.id,
        "company_code": result.company_code,
        "created_by_username": result.created_by_username,
        "created_by_name": result.created_by_name,
        "date": result.date,
        "office": result.office,
        "delivery_place": result.delivery_place,
        "category": result.category,
        "content_type": result.content_type,
        "target_type": result.target_type,
        "target_user": result.target_user,
        "content": result.content,
        "files": json.loads(result.files_json or "[]"),
        "countermeasure": result.countermeasure,
        "approval_status": result.approval_status,
        "reject_reason": result.reject_reason,
    }


def patrol_results_for_current_company():
    query = PatrolResult.query

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    return [
        patrol_result_to_dict(result)
        for result in query.order_by(PatrolResult.id.desc()).all()
    ]

def add_notification(target_user, title, message, link="", files=None):
    if not target_user:
        return

    notification = Notification(
        target_user=target_user,
        title=title,
        message=message,
        link=link,
        files_json=json.dumps(files or [], ensure_ascii=False),
        read=False,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    db.session.add(notification)
    db.session.commit()


def add_news(title, message, files=None, target_type="", target_value=""):
    news = News(
        title=title,
        message=message,
        files_json=json.dumps(files or [], ensure_ascii=False),
        target_type=target_type,
        target_value=target_value,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    db.session.add(news)
    db.session.commit()


def notify_mentions(text, link=""):
    if not text:
        return

    user_query = User.query

    if session.get("role") != "itc":
        user_query = user_query.filter_by(
            company_code=session.get("company_code")
        )

    for user in user_query.all():
        name = user.name

        if not name:
            continue

        mention_text = "@" + name

        if mention_text in text:
            add_notification(
                name,
                "メンションされました",
                text,
                link
            )


def is_same_company_result(result):
    company_code = result.get("company_code")
    return not company_code or company_code == session.get("company_code")


def can_view_patrol_result(result):
    role = session.get("role")

    if role == "itc":
        return True

    if role == "admin":
        return is_same_company_result(result)

    if not is_same_company_result(result):
        return False

    if result.get("target_type") == "delivery_place":
        return True

    if result.get("created_by_username") == session.get("username"):
        return True

    return (
        result.get("target_type") == "user"
        and result.get("target_user") == session.get("name")
    )


def can_manage_patrol_result(result):
    role = session.get("role")

    if role == "itc":
        return True

    return is_same_company_result(result)


def can_approve_patrol_result(result):
    return session.get("role") in ["admin", "itc"] and can_manage_patrol_result(result)


def can_view_checklist_result(result):
    role = session.get("role")
    name = session.get("name")

    if role in ["admin", "itc"]:
        return True

    if result.get("checked_by") == name:
        return True

    return result.get("target_type") == "user" and result.get("target_user") == name


def can_manage_checklist_result(result):
    role = session.get("role")

    if role in ["admin", "itc"]:
        return True

    return result.get("checked_by") == session.get("name")


def can_approve_checklist_result(result):
    return session.get("role") in ["admin", "itc"]


def vehicle_number(vehicle):
    return vehicle.get("number") or (
        f"{vehicle.get('plate_area', '')} "
        f"{vehicle.get('plate_class', '')} "
        f"{vehicle.get('plate_kana', '')} "
        f"{vehicle.get('plate_number', '')}"
    ).strip()


def vehicles_with_numbers():
    query = Vehicle.query.filter_by(deleted=False)

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    vehicles = []

    for vehicle in query.all():
        item = {
            "index": vehicle.id,
            "id": vehicle.id,
            "company_code": vehicle.company_code,
            "vehicle_id": vehicle.vehicle_id,
            "plate_area": vehicle.plate_area,
            "plate_class": vehicle.plate_class,
            "plate_kana": vehicle.plate_kana,
            "plate_number": vehicle.plate_number,
            "type": vehicle.type,
            "office": vehicle.office,
            "inspection_expiry": vehicle.inspection_expiry,
        }

        item["number"] = vehicle_number(item)
        vehicles.append(item)

    return vehicles

def vehicle_types_for_current_company():
    query = VehicleType.query

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    return [
        {
            "id": vehicle_type.id,
            "index": vehicle_type.id,
            "company_code": vehicle_type.company_code,
            "name": vehicle_type.name
        }
        for vehicle_type in query.all()
    ]

def license_types_for_current_company():
    query = LicenseType.query

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    return [
        {
            "id": license_type.id,
            "index": license_type.id,
            "company_code": license_type.company_code,
            "name": license_type.name
        }
        for license_type in query.all()
    ]

def driver_to_dict(driver):
    user = User.query.filter_by(
        company_code=driver.company_code,
        username=driver.employee_id
    ).first()

    return {
        "index": driver.id,
        "id": driver.id,
        "company_code": driver.company_code,
        "employee_id": driver.employee_id,
        "username": user.username if user else driver.employee_id,
        "name": driver.name,
        "role": driver.role,
        "office": driver.office,
        "safe_start_date": driver.safe_start_date,
        "vehicles": json.loads(driver.vehicles_json or "[]"),
        "licenses": json.loads(driver.licenses_json or "[]"),
    }


def drivers_for_current_company():
    query = Driver.query

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    return [
        driver_to_dict(driver)
        for driver in query.all()
    ]

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        company_code = request.form.get("company_code")
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(
            company_code=company_code,
            username=username
        ).first()

        if user and check_password_hash(user.password, password):

            company = get_company(user.company_code)

            if user.role != "itc":
                if not company or not company.active:
                    error = "この会社は現在利用停止中です。ITCへお問い合わせください。"
                else:
                    session.clear()
                    session["company_code"] = user.company_code
                    session["username"] = user.username
                    session["role"] = user.role
                    session["name"] = user.name
                    session["office"] = user.office
                    session["vehicles"] = json.loads(user.favorite_vehicles_json or "[]")

                    return redirect("/")
            else:
                session.clear()
                session["company_code"] = user.company_code
                session["username"] = user.username
                session["role"] = user.role
                session["name"] = user.name
                session["office"] = user.office
                session["vehicles"] = json.loads(user.favorite_vehicles_json or "[]")

                return redirect("/itc")

        else:
            error = "会社コード、ユーザーID、またはパスワードが違います。"

    return render_template("login.html", error=error)

@app.route("/itc/news/new", methods=["GET", "POST"])
def itc_new_news():
    if not require_itc():
        return redirect("/")

    if request.method == "POST":
        title = request.form.get("title")
        message = request.form.get("message")
        target_type = request.form.get("target_type")
        target_value = request.form.get("target_value", "").strip()

        file_names = []

        uploaded_files = request.files.getlist("files")

        for file in uploaded_files:
            if file.filename:
                filename = secure_filename(file.filename)
                save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(save_path)
                file_names.append(filename)

        add_news(
            title,
            message,
            files=file_names,
            target_type=target_type,
            target_value=target_value
        )



        target_users = []

        user_query = User.query

        if target_type == "all":
            target_users = user_query.all()

        elif target_type == "admins":
            target_users = user_query.filter_by(
                role="admin"
            ).all()

        elif target_type == "company":
            target_users = user_query.filter_by(
                company_code=target_value
            ).all()

        elif target_type == "office":
            target_users = user_query.filter_by(
                office=target_value
            ).all()

        elif target_type == "user":
            target_users = user_query.filter_by(
                username=target_value
            ).all()

        for user in target_users:
            add_notification(
                user.name,
                title,
                message,
                "",
                files=file_names
            )
        notify_mentions(message, "/notifications")

        return redirect("/itc")

    return render_template(
        "itc_news_form.html",
        companies=Company.query.all(),
        offices=offices_for_current_company(),
        users=User.query.filter(User.role != "itc").all(),
        news=None,
        mode="new"
    )

@app.route("/itc/news/<int:index>/edit", methods=["GET", "POST"])
def itc_edit_news(index):
    if not require_itc():
        return redirect("/")

    news = News.query.get(index)

    if not news:
        return redirect("/itc")

    if request.method == "POST":
        news.title = request.form.get("title")
        news.message = request.form.get("message")
        news.target_type = request.form.get("target_type")
        news.target_value = request.form.get("target_value", "").strip()

        files = json.loads(news.files_json or "[]")

        uploaded_files = request.files.getlist("files")

        for file in uploaded_files:
            if file.filename:
                filename = secure_filename(file.filename)
                save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(save_path)
                files.append(filename)

        news.files_json = json.dumps(files, ensure_ascii=False)

        db.session.commit()

        return redirect("/itc")

    news_dict = {
        "id": news.id,
        "index": news.id,
        "title": news.title,
        "message": news.message,
        "files": json.loads(news.files_json or "[]"),
        "target_type": news.target_type,
        "target_value": news.target_value,
        "created_at": news.created_at,
    }

    return render_template(
        "itc_news_form.html",
        news=news_dict,
        index=news.id,
        mode="edit",
        companies=Company.query.all(),
        offices=offices_for_current_company(),
        users=User.query.filter(User.role != "itc").all()
    )

@app.route("/itc/news/<int:index>/delete", methods=["POST"])
def itc_delete_news(index):
    if not require_itc():
        return redirect("/")

    news = News.query.get(index)

    if not news:
        return redirect("/itc")

    db.session.delete(news)
    db.session.commit()

    return redirect("/itc")

@app.context_processor
def inject_notification_count():
    user_name = session.get("name")

    unread_count = 0

    if user_name:
        unread_count = Notification.query.filter_by(
            target_user=user_name,
            read=False
        ).count()

    return {
        "unread_notification_count": unread_count
    }


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    company_code_from_url = request.args.get("company_code", "")

    if request.method == "POST":
        company_code = request.form.get("company_code", "").strip()
        name = request.form.get("name", "").strip()
        employee_id = request.form.get("employee_id", "").strip()
        password = request.form.get("password", "").strip()
        office = request.form.get("office", "").strip()
        role = request.form.get("role", "user")

        company = get_company(company_code)

        if not company:
            error = "会社コードが存在しません。"

        elif not company.active:
            error = "この会社は現在利用停止中です。ITCへお問い合わせください。"

        elif role not in ["admin", "user"]:
            error = "ユーザー種別が不正です。"

        elif User.query.filter_by(
            company_code=company_code,
            username=employee_id
        ).first():
            error = "このログインIDはすでに使用されています。"

        else:
            user = User(
                company_code=company_code,
                username=employee_id,
                password=generate_password_hash(password),
                role=role,
                name=name,
                office=office,
                favorite_vehicles_json="[]"
            )

            driver = Driver(
                company_code=company_code,
                employee_id=employee_id,
                name=name,
                role=role,
                office=office,
                safe_start_date=datetime.now().strftime("%Y-%m-%d"),
                vehicles_json="[]",
                licenses_json="[]"
            )

            db.session.add(user)
            db.session.add(driver)
            db.session.commit()

            return redirect("/login")

    company_code = company_code_from_url

    offices = Office.query.filter_by(
        company_code=company_code
    ).all()

    return render_template(
        "register.html",
        error=error,
        company_code=company_code_from_url,
        offices=offices
    )

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/settings", methods=["GET", "POST"])
def settings():
    current_user = User.query.filter_by(
        company_code=session.get("company_code"),
        username=session.get("username")
    ).first()

    if not current_user:
        return redirect("/logout")

    error = None
    success = None

    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        new_password_confirm = request.form.get("new_password_confirm")

        if not check_password_hash(current_user.password, current_password):
            error = "現在のパスワードが違います。"

        elif not new_password:
            error = "新しいパスワードを入力してください。"

        elif new_password != new_password_confirm:
            error = "新しいパスワードが一致しません。"

        else:
            current_user.password = generate_password_hash(new_password)
            db.session.commit()
            success = "パスワードを変更しました。"

    return render_template(
        "settings.html",
        user=current_user,
        error=error,
        success=success
    )

@app.route("/api/news-targets")
def news_targets():
    target_type = request.args.get("type", "")
    keyword = request.args.get("q", "").strip().lower()

    results = []

    if target_type == "company":
        for company in Company.query.all():
            company_name = company.company_name
            company_code = company.company_code

            search_text = (company_name + company_code).lower()

            if keyword and keyword not in search_text:
                continue

            results.append({
                "id": company_code,
                "name": company_name,
                "sub": "会社コード：" + company_code
            })

    elif target_type == "office":
        office_query = Office.query

        for office in office_query.all():
            office_name = office.name or ""
            company_code = office.company_code or ""

            search_text = (office_name + company_code).lower()

            if keyword and keyword not in search_text:
                continue

            results.append({
                "id": office_name,
                "name": office_name,
                "sub": "営業所 / " + company_code
            })

    elif target_type == "user":
        user_query = User.query.filter(User.role != "itc")

        for user in user_query.all():
            user_name = user.name or ""
            username = user.username or ""
            office = user.office or ""
            company_code = user.company_code or ""

            search_text = (
                user_name + username + office + company_code
            ).lower()

            if keyword and keyword not in search_text:
                continue

            results.append({
                "id": username,
                "name": user_name,
                "sub": office + " / " + company_code
            })

    return {"results": results[:10]}

@app.route("/api/mention-users")
def mention_users():
    keyword = request.args.get("q", "").strip()

    users = []

    user_query = User.query

    if session.get("role") != "itc":
        user_query = user_query.filter_by(
            company_code=session.get("company_code")
        )

    for user in user_query.all():
        name = user.name or ""

        if keyword and keyword not in name:
            continue

        users.append({
            "name": name,
            "username": user.username,
            "office": user.office or ""
        })

    for driver in drivers_for_current_company():
        name = driver.get("name", "")

        if keyword and keyword not in name:
            continue

        if not any(u["name"] == name for u in users):
            users.append({
                "name": name,
                "username": driver.get("employee_id"),
                "office": driver.get("office", "")
            })

    return {"users": users[:10]}

@app.route("/")
def dashboard():
    today = datetime.now().date()
    user_name = session.get("name")

    drivers = drivers_for_current_company()

    # 自分の無事故無違反日数
    my_driver = None

    for driver in drivers:
        if driver.get("name") == user_name:
            my_driver = driver
            break

    my_safe_days = 0

    if my_driver and my_driver.get("safe_start_date"):
        start_date = datetime.strptime(
            my_driver["safe_start_date"],
            "%Y-%m-%d"
        ).date()

        my_safe_days = (today - start_date).days

    # 社内ランキング
    ranking = []

    for driver in drivers:
        if not driver.get("safe_start_date"):
            continue

        start_date = datetime.strptime(
            driver["safe_start_date"],
            "%Y-%m-%d"
        ).date()

        safe_days = (today - start_date).days

        item = driver.copy()
        item["safe_days"] = safe_days
        ranking.append(item)

    ranking = sorted(
        ranking,
        key=lambda x: x.get("safe_days", 0),
        reverse=True
    )[:10]

    # 自分のGood件数
    my_good_count = PatrolResult.query.filter_by(
        company_code=session.get("company_code"),
        category="Good",
        target_user=user_name
    ).count()

    # 自分に対する未対応指摘
    my_pending_pointouts = []

    pending_records = PatrolResult.query.filter_by(
        company_code=session.get("company_code"),
        target_type="user",
        target_user=user_name
    ).filter(
        PatrolResult.approval_status != "承認済み"
    ).order_by(
        PatrolResult.id.desc()
    ).all()

    for record in pending_records:
        my_pending_pointouts.append(
            patrol_result_to_dict(record)
        )

    # 車検が近い車両
    inspection_alerts = []

    for vehicle in vehicles_with_numbers():
        expiry = vehicle.get("inspection_expiry")

        if not expiry:
            continue

        expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        remaining_days = (expiry_date - today).days

        if remaining_days <= 90:
            item = vehicle.copy()
            item["remaining_days"] = remaining_days
            inspection_alerts.append(item)

    inspection_alerts = sorted(
        inspection_alerts,
        key=lambda x: x.get("remaining_days", 9999)
    )

    setup_tasks = []

    if session.get("role") == "admin":
        company_code = session.get("company_code")

        if Office.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "営業所マスタ",
                "description": "営業所を登録してください。",
                "url": "/master/offices"
            })

        if VehicleType.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "車種マスタ",
                "description": "車両登録で使用する車種を登録してください。",
                "url": "/master/vehicle-types"
            })

        if LicenseType.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "免許種別マスタ",
                "description": "ドライバー登録で使用する免許種別を登録してください。",
                "url": "/master/license-types"
            })

        if DeliveryPlace.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "納入先マスタ",
                "description": "安全パトロールで使用する納入先を登録してください。",
                "url": "/master/delivery-places"
            })

        if Vehicle.query.filter_by(
            company_code=company_code,
            deleted=False
        ).count() == 0:
            setup_tasks.append({
                "name": "車両マスタ",
                "description": "車両管理・点検で使用する車両を登録してください。",
                "url": "/master/vehicles"
            })

        if Checklist.query.filter_by(company_code=company_code).count() == 0:
            setup_tasks.append({
                "name": "チェックリストマスタ",
                "description": "安全管理・車両管理で使用するチェックリストを登録してください。",
                "url": "/master/checklists"
            })

    return render_template(
        "index.html",
        my_safe_days=my_safe_days,
        ranking=ranking,
        my_good_count=my_good_count,
        my_pending_pointouts=my_pending_pointouts,
        inspection_alerts=inspection_alerts,
        setup_tasks=setup_tasks
    )

@app.route("/notifications")
def notifications():
    user_name = session.get("name")

    items = []

    notification_records = Notification.query.filter_by(
        target_user=user_name
    ).order_by(Notification.id.desc()).all()

    for notification in notification_records:
        items.append({
            "id": notification.id,
            "index": notification.id,
            "target_user": notification.target_user,
            "title": notification.title,
            "message": notification.message,
            "link": notification.link,
            "files": json.loads(notification.files_json or "[]"),
            "read": notification.read,
            "created_at": notification.created_at,
        })

    return render_template(
        "notifications.html",
        notifications=items
    )

@app.route("/notifications/<int:index>")
def notification_detail(index):
    notification = Notification.query.get(index)

    if not notification:
        return redirect("/notifications")

    if notification.target_user != session.get("name"):
        return redirect("/notifications")

    notification.read = True
    db.session.commit()

    notification_dict = {
        "id": notification.id,
        "index": notification.id,
        "target_user": notification.target_user,
        "title": notification.title,
        "message": notification.message,
        "link": notification.link,
        "files": json.loads(notification.files_json or "[]"),
        "read": notification.read,
        "created_at": notification.created_at,
    }

    return render_template(
        "notification_detail.html",
        notification=notification_dict,
        index=notification.id
    )

@app.route("/notifications/<int:index>/delete", methods=["POST"])
def delete_notification(index):
    notification = Notification.query.get(index)

    if not notification:
        return redirect("/notifications")

    if notification.target_user != session.get("name"):
        return redirect("/notifications")

    db.session.delete(notification)
    db.session.commit()

    return redirect("/notifications")

@app.route("/itc")
def itc_dashboard():
    if not require_itc():
        return redirect("/")

    company_summaries = []

    companies = Company.query.all()

    for company in companies:
        company_code = company.company_code

        vehicle_count = Vehicle.query.filter_by(
            company_code=company_code,
            deleted=False
        ).count()

        item = {
            "id": company.id,
            "company_code": company.company_code,
            "company_name": company.company_name,
            "vehicle_limit": company.vehicle_limit,
            "active": company.active,
            "vehicle_count": vehicle_count,
            "remaining_vehicles": company.vehicle_limit - vehicle_count,
        }

        company_summaries.append(item)

    news_items = []

    for news in News.query.order_by(News.id.desc()).all():
        news_items.append({
            "id": news.id,
            "index": news.id,
            "title": news.title,
            "message": news.message,
            "files": json.loads(news.files_json or "[]"),
            "target_type": news.target_type,
            "target_value": news.target_value,
            "created_at": news.created_at,
        })

    return render_template(
        "itc_dashboard.html",
        companies=company_summaries,
        news=news_items
    )

@app.route("/itc/companies/new", methods=["GET", "POST"])
def itc_new_company():
    if not require_itc():
        return redirect("/")

    if request.method == "POST":
        company = Company(
            company_code=request.form.get("company_code"),
            company_name=request.form.get("company_name"),
            vehicle_limit=int(request.form.get("vehicle_limit") or 0),
            active=True,
        )

        db.session.add(company)
        db.session.commit()

        return redirect("/itc")

    return render_template(
        "itc_company_form.html",
        company=None,
        index=None,
        mode="new"
    )

@app.route("/itc/companies/<int:index>/edit", methods=["GET", "POST"])
def itc_edit_company(index):
    if not require_itc():
        return redirect("/")

    company = Company.query.get(index)

    if not company:
        return redirect("/itc")

    if request.method == "POST":
        company.company_code = request.form.get("company_code")
        company.company_name = request.form.get("company_name")
        company.vehicle_limit = int(request.form.get("vehicle_limit") or 0)
        company.active = request.form.get("active") == "1"

        db.session.commit()

        return redirect("/itc")

    company_dict = {
        "company_code": company.company_code,
        "company_name": company.company_name,
        "vehicle_limit": company.vehicle_limit,
        "active": company.active,
    }

    return render_template(
        "itc_company_form.html",
        company=company_dict,
        index=company.id,
        mode="edit"
    )

@app.route("/safety")
def safety():
    return render_template("safety.html")

@app.route("/pointouts")
def pointouts():
    role = session.get("role")

    view_type = request.args.get("type", "user")
    if view_type not in PATROL_VIEW_TYPES:
        view_type = "user"

    keyword = request.args.get("keyword", "").strip()

    visible_results = []

    for result in patrol_results_for_current_company():
        if result.get("target_type") != view_type:
            continue

        if not can_view_patrol_result(result):
            continue

        if (
            keyword
            and view_type == "user"
            and keyword not in result.get("target_user", "")
        ):
            continue

        if (
            keyword
            and view_type == "delivery_place"
            and keyword not in result.get("delivery_place", "")
        ):
            continue

        result["can_manage"] = can_manage_patrol_result(result)
        visible_results.append(result)

    return render_template(
        "pointouts.html",
        patrol_results=visible_results,
        view_type=view_type,
        keyword=keyword,
        role=role,
        show_target_user=view_type == "user",
        drivers=drivers_for_current_company(),
        delivery_places=delivery_places_for_current_company(),
    )


@app.route("/pointouts/new", methods=["GET", "POST"])
def new_pointout():
    if request.method == "POST":
        uploaded_files = request.files.getlist("files")

        file_names = []

        for file in uploaded_files:
            if file.filename:
                filename = secure_filename(file.filename)
                save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(save_path)
                file_names.append(filename)

        target_type = request.form.get("target_type")

        if target_type not in PATROL_VIEW_TYPES:
            target_type = "user"

        result = PatrolResult(
            company_code=session.get("company_code"),
            created_by_username=session.get("username"),
            created_by_name=session.get("name"),
            date=request.form.get("date"),
            office=session.get("office"),
            category=request.form.get("category"),
            content_type=request.form.get("content_type"),
            target_type=target_type,
            target_user=request.form.get("target_user") if target_type == "user" else "",
            delivery_place=request.form.get("delivery_place") if target_type == "delivery_place" else "",
            content=request.form.get("content"),
            files_json=json.dumps(file_names, ensure_ascii=False),
            countermeasure="",
            approval_status="未対応",
            reject_reason=""
        )

        db.session.add(result)
        db.session.commit()

        add_notification(
            result.target_user,
            "安全パトロール確認依頼",
            "あなたに確認が必要な安全パトロールがあります。",
            f"/pointouts/{result.id}"
        )

        notify_mentions(
            result.content,
            f"/pointouts/{result.id}"
        )

        if target_type == "delivery_place":
            return redirect("/pointouts?type=delivery_place")

        return redirect("/pointouts?type=user")

    return render_template(
        "new_pointout.html",
        drivers=drivers_for_current_company(),
        delivery_places=delivery_places_for_current_company(),
        manuals=manuals_for_current_company(),
    )

@app.route("/pointouts/<int:index>")
def pointout_detail(index):
    result_record = PatrolResult.query.get(index)

    if not result_record:
        return redirect("/pointouts")

    result = patrol_result_to_dict(result_record)

    if not can_view_patrol_result(result):
        return redirect("/pointouts")

    return render_template(
        "pointout_detail.html",
        result=result,
        index=result_record.id,
        manuals=manuals_for_current_company(),
        can_manage=can_manage_patrol_result(result),
        can_approve=can_approve_patrol_result(result),
    )

@app.route("/pointouts/<int:index>/edit", methods=["GET", "POST"])
def edit_pointout(index):

    result_record = PatrolResult.query.get(index)

    if not result_record:
        return redirect("/pointouts")

    result = patrol_result_to_dict(result_record)

    if not can_manage_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    if request.method == "POST":

        result_record.date = request.form.get("date")
        result_record.category = request.form.get("category")
        result_record.content_type = request.form.get("content_type")
        result_record.content = request.form.get("content")

        if result_record.target_type == "user":
            result_record.target_user = request.form.get("target_user")

        if result_record.target_type == "delivery_place":
            result_record.delivery_place = request.form.get("delivery_place")

        files = json.loads(result_record.files_json or "[]")

        delete_files = request.form.getlist("delete_files")

        for delete_file in delete_files:
            if delete_file in files:
                files.remove(delete_file)

                file_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    delete_file
                )

                if os.path.exists(file_path):
                    os.remove(file_path)

        uploaded_files = request.files.getlist("files")

        for file in uploaded_files:
            if file.filename:
                filename = secure_filename(file.filename)

                save_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    filename
                )

                file.save(save_path)
                files.append(filename)

        result_record.files_json = json.dumps(
            files,
            ensure_ascii=False
        )

        db.session.commit()

        return redirect(f"/pointouts/{result_record.id}")

    return render_template(
        "edit_pointout.html",
        result=result,
        index=result_record.id,
        drivers=drivers_for_current_company(),
        delivery_places=delivery_places_for_current_company(),
        manuals=manuals_for_current_company(),
    )

@app.route("/pointouts/<int:index>/countermeasure/new")
def new_countermeasure(index):
    result_record = PatrolResult.query.get(index)

    if not result_record:
        return redirect("/pointouts")

    result = patrol_result_to_dict(result_record)

    if not can_manage_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    return render_template(
        "countermeasure.html",
        result=result,
        index=result_record.id
    )


@app.route("/pointouts/<int:index>/countermeasure", methods=["POST"])
def register_countermeasure(index):
    result_record = PatrolResult.query.get(index)

    if not result_record:
        return redirect("/pointouts")

    result = patrol_result_to_dict(result_record)

    if not can_manage_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    result_record.countermeasure = request.form.get("countermeasure")
    result_record.countermeasure_by = session.get("name")
    result_record.approval_status = "承認待ち"
    result_record.reject_reason = ""

    db.session.commit()

    return redirect(f"/pointouts/{result_record.id}")


@app.route("/pointouts/<int:index>/approve", methods=["POST"])
def approve_countermeasure(index):
    result_record = PatrolResult.query.get(index)

    if not result_record:
        return redirect("/pointouts")

    result = patrol_result_to_dict(result_record)

    if not can_approve_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    result_record.approval_status = "承認済み"
    result_record.reject_reason = ""

    db.session.commit()

    return redirect(f"/pointouts/{result_record.id}")


@app.route("/pointouts/<int:index>/reject", methods=["POST"])
def reject_countermeasure(index):
    result_record = PatrolResult.query.get(index)

    if not result_record:
        return redirect("/pointouts")

    result = patrol_result_to_dict(result_record)

    if not can_approve_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    reject_reason = request.form.get("reject_reason", "")

    result_record.approval_status = "差し戻し"
    result_record.reject_reason = reject_reason

    notify_users = set()

    if result_record.created_by_name:
        notify_users.add(result_record.created_by_name)

    if result_record.target_user:
        notify_users.add(result_record.target_user)

    if result_record.countermeasure_by:
        notify_users.add(result_record.countermeasure_by)

    for target_user in notify_users:
        add_notification(
            target_user,
            "安全パトロールが差し戻されました",
            reject_reason or "安全パトロールが差し戻されました。",
            f"/pointouts/{result_record.id}"
        )

    db.session.commit()

    return redirect(f"/pointouts/{result_record.id}")


@app.route("/pointouts/<int:index>/delete", methods=["POST"])
def delete_pointout(index):
    result_record = PatrolResult.query.get(index)

    if not result_record:
        return redirect("/pointouts")

    result = patrol_result_to_dict(result_record)

    if not can_manage_patrol_result(result):
        return redirect(f"/pointouts/{index}")

    view_type = result.get("target_type", "user")

    db.session.delete(result_record)
    db.session.commit()

    return redirect(f"/pointouts?type={view_type}")

@app.route("/vehicle-patrols/new", methods=["GET", "POST"])
def new_vehicle_patrol():

    if request.method == "POST":

        patrol = VehiclePatrol(
            company_code=session.get("company_code"),
            vehicle_id=request.form.get("vehicle_id"),
            occurred_date=request.form.get("occurred_date"),
            category=request.form.get("category"),
            priority=request.form.get("priority"),
            content=request.form.get("content"),
            cause=request.form.get("cause"),
            temporary_action=request.form.get("temporary_action"),
            repair_content=request.form.get("repair_content"),
            status=request.form.get("status", "未対応"),
            repair_date=request.form.get("repair_date"),
            repair_person=request.form.get("repair_person"),
            repair_time=request.form.get("repair_time"),
            parts=request.form.get("parts"),
            cost=request.form.get("cost")
        )

        db.session.add(patrol)
        db.session.commit()

        return redirect("/vehicle-patrols")

    return render_template(
        "vehicle_patrol_form.html",
        patrol=None,
        vehicles=vehicles_with_numbers(),
        mode="new"
    )


@app.route("/vehicle-favorites/add", methods=["POST"])
def add_vehicle_favorite():
    vehicle_id = request.form.get("vehicle_id")

    if not vehicle_id:
        return redirect("/vehicle-patrols")

    current_user = User.query.filter_by(
        company_code=session.get("company_code"),
        username=session.get("username")
    ).first()

    if not current_user:
        return redirect("/logout")

    favorite_vehicles = json.loads(
        current_user.favorite_vehicles_json or "[]"
    )

    if vehicle_id not in favorite_vehicles:
        favorite_vehicles.append(vehicle_id)

    current_user.favorite_vehicles_json = json.dumps(
        favorite_vehicles,
        ensure_ascii=False
    )

    db.session.commit()

    session["vehicles"] = favorite_vehicles

    return redirect("/vehicle-patrols")

@app.route("/vehicle-favorites/remove/<vehicle_id>", methods=["POST"])
def remove_vehicle_favorite(vehicle_id):
    current_user = User.query.filter_by(
        company_code=session.get("company_code"),
        username=session.get("username")
    ).first()

    if not current_user:
        return redirect("/logout")

    favorite_vehicles = json.loads(
        current_user.favorite_vehicles_json or "[]"
    )

    if vehicle_id in favorite_vehicles:
        favorite_vehicles.remove(vehicle_id)

    current_user.favorite_vehicles_json = json.dumps(
        favorite_vehicles,
        ensure_ascii=False
    )

    db.session.commit()

    session["vehicles"] = favorite_vehicles

    return redirect("/vehicle-patrols")

@app.route("/vehicle-patrols")
def vehicle_patrols():

    keyword = request.args.get("keyword", "").strip()
    status_filter = request.args.get("status", "active")

    favorite_vehicles = session.get("vehicles", [])

    favorite_patrols = []
    other_patrols = []

    for patrol in vehicle_patrols_for_current_company():

        if status_filter == "active":
            if patrol.get("status") == "修理完了":
                continue
        elif status_filter:
            if patrol.get("status") != status_filter:
                continue

        if keyword:
            search_text = (
                str(patrol.get("vehicle_id", "")) +
                str(patrol.get("content", "")) +
                str(patrol.get("repair_person", ""))
            ).lower()

            if keyword.lower() not in search_text:
                continue

        if patrol.get("vehicle_id") in favorite_vehicles:
            favorite_patrols.append(patrol)
        else:
            other_patrols.append(patrol)

    return render_template(
        "vehicle_patrols.html",
        favorite_patrols=favorite_patrols,
        other_patrols=other_patrols,
        favorite_vehicles=favorite_vehicles,
        vehicles=vehicles_with_numbers(),
        keyword=keyword,
        status_filter=status_filter
    )

@app.route("/vehicle-patrols/<int:index>")
def vehicle_patrol_detail(index):

    patrol = VehiclePatrol.query.get(index)

    if not patrol:
        return redirect("/vehicle-patrols")

    if session.get("role") != "itc":
        if patrol.company_code != session.get("company_code"):
            return redirect("/vehicle-patrols")

    return render_template(
        "vehicle_patrol_detail.html",
        patrol=vehicle_patrol_to_dict(patrol),
        index=patrol.id
    )

@app.route("/vehicle-patrols/<int:index>/edit", methods=["GET", "POST"])
def edit_vehicle_patrol(index):

    patrol = VehiclePatrol.query.get(index)

    if not patrol:
        return redirect("/vehicle-patrols")

    if session.get("role") != "itc":
        if patrol.company_code != session.get("company_code"):
            return redirect("/vehicle-patrols")

    if request.method == "POST":

        patrol.vehicle_id = request.form.get("vehicle_id")
        patrol.occurred_date = request.form.get("occurred_date")
        patrol.category = request.form.get("category")
        patrol.priority = request.form.get("priority")
        patrol.content = request.form.get("content")

        patrol.cause = request.form.get("cause")
        patrol.temporary_action = request.form.get("temporary_action")
        patrol.repair_content = request.form.get("repair_content")

        patrol.repair_date = request.form.get("repair_date")
        patrol.repair_person = request.form.get("repair_person")
        patrol.repair_time = request.form.get("repair_time")
        patrol.parts = request.form.get("parts")
        patrol.cost = request.form.get("cost")
        patrol.status = request.form.get("status", "未対応")

        db.session.commit()

        return redirect(f"/vehicle-patrols/{patrol.id}")

    return render_template(
        "vehicle_patrol_form.html",
        patrol=vehicle_patrol_to_dict(patrol),
        index=patrol.id,
        vehicles=vehicles_with_numbers(),
        mode="edit"
    )

@app.route("/vehicle-patrols/<int:index>/delete", methods=["POST"])
def delete_vehicle_patrol(index):

    patrol = VehiclePatrol.query.get(index)

    if not patrol:
        return redirect("/vehicle-patrols")

    if session.get("role") != "itc":
        if patrol.company_code != session.get("company_code"):
            return redirect("/vehicle-patrols")

    db.session.delete(patrol)
    db.session.commit()

    return redirect("/vehicle-patrols")

@app.route("/master/vehicle-types")
def vehicle_type_master():
    return render_template(
        "vehicle_type_master.html",
        vehicle_types=vehicle_types_for_current_company()
    )

@app.route("/master/license-types")
def license_type_master():
    return render_template(
        "license_type_master.html",
        license_types=license_types_for_current_company()
    )


@app.route("/master/license-types/new", methods=["GET", "POST"])
def new_license_type():
    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if LicenseType.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first():
            return "この免許種別はすでに登録されています。"

        license_type = LicenseType(
            company_code=session.get("company_code"),
            name=name
        )

        db.session.add(license_type)
        db.session.commit()

        return redirect("/master/license-types")

    return render_template(
        "license_type_form.html",
        license_type=None,
        mode="new"
    )


@app.route("/master/license-types/<int:index>/edit", methods=["GET", "POST"])
def edit_license_type(index):
    license_type = LicenseType.query.get(index)

    if not license_type:
        return redirect("/master/license-types")

    if session.get("role") != "itc":
        if license_type.company_code != session.get("company_code"):
            return redirect("/master/license-types")

    if request.method == "POST":
        license_type.name = request.form.get("name")

        db.session.commit()

        return redirect("/master/license-types")

    return render_template(
        "license_type_form.html",
        license_type={
            "id": license_type.id,
            "name": license_type.name
        },
        mode="edit"
    )


@app.route("/master/license-types/<int:index>/delete", methods=["POST"])
def delete_license_type(index):
    license_type = LicenseType.query.get(index)

    if not license_type:
        return redirect("/master/license-types")

    if session.get("role") != "itc":
        if license_type.company_code != session.get("company_code"):
            return redirect("/master/license-types")
        
    for driver in Driver.query.filter_by(
        company_code=license_type.company_code
    ).all():
        licenses = json.loads(driver.licenses_json or "[]")

        licenses = [
            license
            for license in licenses
            if license.get("type") != license_type.name
        ]

        driver.licenses_json = json.dumps(
            licenses,
            ensure_ascii=False
        )

    db.session.delete(license_type)
    db.session.commit()

    return redirect("/master/license-types")

@app.route("/master/vehicle-types/new", methods=["GET", "POST"])
def new_vehicle_type():
    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if VehicleType.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first():
            return "この車種はすでに登録されています。"

        vehicle_type = VehicleType(
            company_code=session.get("company_code"),
            name=name
        )

        db.session.add(vehicle_type)
        db.session.commit()

        return redirect("/master/vehicle-types")

    return render_template(
        "vehicle_type_form.html",
        vehicle_type=None,
        mode="new"
    )


@app.route("/master/vehicle-types/<int:index>/edit", methods=["GET", "POST"])
def edit_vehicle_type(index):
    vehicle_type = VehicleType.query.get(index)

    if not vehicle_type:
        return redirect("/master/vehicle-types")

    if session.get("role") != "itc":
        if vehicle_type.company_code != session.get("company_code"):
            return redirect("/master/vehicle-types")

    if request.method == "POST":
        vehicle_type.name = request.form.get("name")
        db.session.commit()

        return redirect("/master/vehicle-types")

    return render_template(
        "vehicle_type_form.html",
        vehicle_type={
            "id": vehicle_type.id,
            "name": vehicle_type.name
        },
        mode="edit"
    )


@app.route("/master/vehicle-types/<int:index>/delete", methods=["POST"])
def delete_vehicle_type(index):
    vehicle_type = VehicleType.query.get(index)

    if not vehicle_type:
        return redirect("/master/vehicle-types")

    if session.get("role") != "itc":
        if vehicle_type.company_code != session.get("company_code"):
            return redirect("/master/vehicle-types")

    for vehicle in Vehicle.query.filter_by(
        company_code=vehicle_type.company_code,
        type=vehicle_type.name,
        deleted=False
    ).all():
        vehicle.type = ""

    db.session.delete(vehicle_type)
    db.session.commit()

    return redirect("/master/vehicle-types")

@app.route("/vehicle")
def vehicle():
    return render_template("vehicle.html")


@app.route("/analysis")
def analysis():
    return render_template("analysis.html")


@app.route("/manuals")
def manuals():
    return render_template("manuals.html")


@app.route("/master")
def master():
    return render_template("master_menu.html")

@app.route("/master/offices")
def office_master():
    return render_template(
        "office_master.html",
        offices=offices_for_current_company()
    )

@app.route("/master/offices/new", methods=["GET", "POST"])
def new_office():
    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if Office.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first():
            return "この営業所はすでに登録されています。"

        office = Office(
            company_code=session.get("company_code"),
            name=name
        )

        db.session.add(office)
        db.session.commit()

        return redirect("/master/offices")

    return render_template(
        "office_form.html",
        office=None,
        index=None,
        mode="new"
    )


@app.route("/master/offices/<int:index>/edit", methods=["GET", "POST"])
def edit_office(index):
    office = Office.query.get(index)

    if not office:
        return redirect("/master/offices")

    if session.get("role") != "itc":
        if office.company_code != session.get("company_code"):
            return redirect("/master/offices")

    if request.method == "POST":
        office.name = request.form.get("name")
        db.session.commit()

        return redirect("/master/offices")

    office_dict = {
        "id": office.id,
        "index": office.id,
        "company_code": office.company_code,
        "name": office.name
    }

    return render_template(
        "office_form.html",
        office=office_dict,
        index=office.id,
        mode="edit"
    )


@app.route("/master/offices/<int:index>/delete", methods=["POST"])
def delete_office(index):
    office = Office.query.get(index)

    if not office:
        return redirect("/master/offices")

    if session.get("role") != "itc":
        if office.company_code != session.get("company_code"):
            return redirect("/master/offices")

    for driver in Driver.query.filter_by(
        company_code=office.company_code,
        office=office.name
    ).all():
        driver.office = ""

    for user in User.query.filter_by(
        company_code=office.company_code,
        office=office.name
    ).all():
        user.office = ""

    for vehicle in Vehicle.query.filter_by(
        company_code=office.company_code,
        office=office.name,
        deleted=False
    ).all():
        vehicle.office = ""

    db.session.delete(office)
    db.session.commit()

    return redirect("/master/offices")

@app.route("/master/delivery-places")
def delivery_place_master():
    return render_template(
        "delivery_place_master.html",
        delivery_places=delivery_places_for_current_company()
    )


@app.route("/master/delivery-places/new", methods=["GET", "POST"])
def new_delivery_place():
    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if DeliveryPlace.query.filter_by(
            company_code=session.get("company_code"),
            name=name
        ).first():
            return "この納入先はすでに登録されています。"

        place = DeliveryPlace(
            company_code=session.get("company_code"),
            name=name
        )

        db.session.add(place)
        db.session.commit()

        return redirect("/master/delivery-places")

    return render_template(
        "delivery_place_form.html",
        place=None,
        index=None,
        mode="new"
    )


@app.route("/master/delivery-places/<int:index>/edit", methods=["GET", "POST"])
def edit_delivery_place(index):
    place = DeliveryPlace.query.get(index)

    if not place:
        return redirect("/master/delivery-places")

    if session.get("role") != "itc":
        if place.company_code != session.get("company_code"):
            return redirect("/master/delivery-places")

    if request.method == "POST":
        place.name = request.form.get("name")
        db.session.commit()

        return redirect("/master/delivery-places")

    return render_template(
        "delivery_place_form.html",
        place={
            "id": place.id,
            "index": place.id,
            "company_code": place.company_code,
            "name": place.name
        },
        index=place.id,
        mode="edit"
    )


@app.route("/master/delivery-places/<int:index>/delete", methods=["POST"])
def delete_delivery_place(index):
    place = DeliveryPlace.query.get(index)

    if not place:
        return redirect("/master/delivery-places")

    if session.get("role") != "itc":
        if place.company_code != session.get("company_code"):
            return redirect("/master/delivery-places")

    db.session.delete(place)
    db.session.commit()

    return redirect("/master/delivery-places")

@app.route("/master/drivers")
def driver_master():
    keyword = request.args.get("keyword", "")
    office = request.args.get("office", "")
    vehicle = request.args.get("vehicle", "")

    filtered_drivers = []

    drivers = drivers_for_current_company()

    for driver in drivers:
        if keyword:
            if (
                keyword not in driver["employee_id"]
                and keyword not in driver["name"]
            ):
                continue

        if office:
            if driver["office"] != office:
                continue

        if vehicle:
            if vehicle not in driver["vehicles"]:
                continue

        safe_start_date = driver.get("safe_start_date")

        if safe_start_date:
            start_date = datetime.strptime(
                safe_start_date,
                "%Y-%m-%d"
            )

            days = (datetime.today() - start_date).days
        else:
            days = 0

        years = days // 365
        remaining_days = days % 365

        driver_item = driver.copy()
        driver_item["safe_days_display"] = (
            f"{years}年{remaining_days}日継続中"
            if years > 0
            else f"{days}日継続中"
        )

        filtered_drivers.append(driver_item)

    return render_template(
        "driver_master.html",
        drivers=filtered_drivers,
        offices=offices_for_current_company(),
        vehicles=vehicles_with_numbers(),
        keyword=keyword,
        office=office,
        vehicle=vehicle,
    )

@app.route("/master/drivers/new", methods=["GET", "POST"])
def new_driver():
    if request.method == "POST":
        employee_id = request.form.get("employee_id")

        if User.query.filter_by(
            company_code=session.get("company_code"),
            username=employee_id
        ).first():
            return "このログインIDはすでに使用されています。"
        licenses = []

        license_types = request.form.getlist("license_type")
        license_expiries = request.form.getlist("license_expiry")

        for license_type, expiry in zip(license_types, license_expiries):
            if license_type and expiry:
                licenses.append({
                    "type": license_type,
                    "expiry": expiry
                })

        driver = Driver(
            company_code=session.get("company_code"),
            employee_id=request.form.get("employee_id"),
            name=request.form.get("name"),
            role=request.form.get("role"),
            office=request.form.get("office"),
            safe_start_date=request.form.get("safe_start_date"),
            vehicles_json=json.dumps(
                request.form.getlist("vehicles"),
                ensure_ascii=False
            ),
            licenses_json=json.dumps(
                licenses,
                ensure_ascii=False
            )
        )
        user = User(
            company_code=session.get("company_code"),
            username=request.form.get("employee_id"),
            password=generate_password_hash(request.form.get("password")),
            role=request.form.get("role"),
            name=request.form.get("name"),
            office=request.form.get("office"),
            favorite_vehicles_json=json.dumps(
                request.form.getlist("vehicles"),
                ensure_ascii=False
            )
        )

        db.session.add(user)

        db.session.add(driver)
        db.session.commit()

        return redirect("/master/drivers")

    return render_template(
        "driver_form.html",
        driver=None,
        offices=offices_for_current_company(),
        vehicles=vehicles_with_numbers(),
        license_types=license_types_for_current_company(),
        mode="new"
    )

@app.route("/master/drivers/<int:index>/edit", methods=["GET", "POST"])
def edit_driver(index):
    driver = Driver.query.get(index)

    if not driver:
        return redirect("/master/drivers")

    if session.get("role") != "itc":
        if driver.company_code != session.get("company_code"):
            return redirect("/master/drivers")

    if request.method == "POST":
        licenses = []

        license_types = request.form.getlist("license_type")
        license_expiries = request.form.getlist("license_expiry")

        for license_type, expiry in zip(license_types, license_expiries):
            if license_type:
                licenses.append({
                    "type": license_type,
                    "expiry": expiry
                })

        old_employee_id = driver.employee_id

        new_employee_id = request.form.get("employee_id")

        if new_employee_id != old_employee_id:
            existing_user = User.query.filter_by(
                company_code=driver.company_code,
                username=new_employee_id
            ).first()

            if existing_user:
                return "このログインIDはすでに使用されています。"

        driver.employee_id = new_employee_id
        driver.name = request.form.get("name")
        driver.role = request.form.get("role")
        driver.office = request.form.get("office")
        driver.safe_start_date = request.form.get("safe_start_date")
        driver.vehicles_json = json.dumps(
            request.form.getlist("vehicles"),
            ensure_ascii=False
        )
        driver.licenses_json = json.dumps(
            licenses,
            ensure_ascii=False
        )
        user = User.query.filter_by(
            company_code=driver.company_code,
            username=old_employee_id
        ).first()

        if not user:
            user = User(
                company_code=driver.company_code,
                username=request.form.get("employee_id"),
                password=generate_password_hash(request.form.get("password") or "password"),
                role=request.form.get("role"),
                name=request.form.get("name"),
                office=request.form.get("office"),
                favorite_vehicles_json="[]"
            )
            db.session.add(user)

        user.username = request.form.get("employee_id")
        user.role = request.form.get("role")
        user.name = request.form.get("name")
        user.office = request.form.get("office")
        user.favorite_vehicles_json = json.dumps(
            request.form.getlist("vehicles"),
            ensure_ascii=False
        )

        if request.form.get("password"):
            user.password = generate_password_hash(request.form.get("password"))

        db.session.commit()

        return redirect("/master/drivers")

    driver_dict = driver_to_dict(driver)

    return render_template(
        "driver_form.html",
        driver=driver_dict,
        index=driver.id,
        offices=offices_for_current_company(),
        vehicles=vehicles_with_numbers(),
        license_types=license_types_for_current_company(),
        mode="edit"
    )


@app.route("/master/drivers/<int:index>/delete", methods=["POST"])
def delete_driver(index):
    driver = Driver.query.get(index)

    if not driver:
        return redirect("/master/drivers")

    if session.get("role") != "itc":
        if driver.company_code != session.get("company_code"):
            return redirect("/master/drivers")

    user = User.query.filter_by(
        company_code=driver.company_code,
        username=driver.employee_id
    ).first()

    if user:
        db.session.delete(user)

    db.session.delete(driver)
    db.session.commit()

    return redirect("/master/drivers")

@app.route("/master/vehicles")
def vehicle_master():
    keyword = request.args.get("keyword", "").strip()
    office = request.args.get("office", "").strip()
    vehicle_type = request.args.get("vehicle_type", "").strip()

    vehicles = vehicles_with_numbers()
    filtered_vehicles = []

    for vehicle in vehicles:
        if keyword:
            search_text = (
                str(vehicle.get("vehicle_id", "")) +
                str(vehicle.get("plate_area", "")) +
                str(vehicle.get("plate_class", "")) +
                str(vehicle.get("plate_kana", "")) +
                str(vehicle.get("plate_number", ""))
            )

            if keyword not in search_text:
                continue

        if office and vehicle.get("office") != office:
            continue

        if vehicle_type and vehicle.get("type") != vehicle_type:
            continue

        filtered_vehicles.append(vehicle)

    company = Company.query.filter_by(
        company_code=session.get("company_code")
    ).first()

    vehicle_limit = 0
    vehicle_count = len(vehicles)
    remaining_vehicles = 0

    if company:
        vehicle_limit = company.vehicle_limit
        remaining_vehicles = vehicle_limit - vehicle_count

    return render_template(
        "vehicle_master.html",
        vehicles=filtered_vehicles,
        offices=offices_for_current_company(),
        vehicle_types=vehicle_types_for_current_company(),
        keyword=keyword,
        office=office,
        vehicle_type=vehicle_type,

        vehicle_limit=vehicle_limit,
        vehicle_count=vehicle_count,
        remaining_vehicles=remaining_vehicles,
    )


@app.route("/master/vehicles/new", methods=["GET", "POST"])
def new_vehicle():
    if request.method == "POST":
        company_code = session.get("company_code")

        if session.get("role") == "itc":
            company_code = request.form.get("company_code") or "AAA"

        vehicle_count = Vehicle.query.filter_by(
            company_code=company_code,
            deleted=False
        ).count()

        company = Company.query.filter_by(
            company_code=company_code
        ).first()

        if company:
            if vehicle_count >= company.vehicle_limit:
                return "登録可能台数の上限に達しています。"

        all_vehicle_count = Vehicle.query.filter_by(
            company_code=company_code
        ).count()

        new_id = f"V{all_vehicle_count + 1:03}"

        vehicle = Vehicle(
            company_code=company_code,
            vehicle_id=new_id,
            plate_area=request.form.get("plate_area"),
            plate_class=request.form.get("plate_class"),
            plate_kana=request.form.get("plate_kana"),
            plate_number=request.form.get("plate_number"),
            type=request.form.get("type"),
            office=request.form.get("office"),
            inspection_expiry=request.form.get("inspection_expiry"),
        )

        db.session.add(vehicle)
        db.session.commit()

        return redirect("/master/vehicles")

    return render_template(
        "vehicle_form.html",
        vehicle=None,
        offices=offices_for_current_company(),
        vehicle_types=vehicle_types_for_current_company(),
        mode="new"
    )


@app.route("/master/vehicles/<int:index>/edit", methods=["GET", "POST"])
def edit_vehicle(index):
    vehicle = Vehicle.query.get(index)

    if not vehicle:
        return redirect("/master/vehicles")

    if session.get("role") != "itc":
        if vehicle.company_code != session.get("company_code"):
            return redirect("/master/vehicles")

    if request.method == "POST":
        vehicle.plate_area = request.form.get("plate_area")
        vehicle.plate_class = request.form.get("plate_class")
        vehicle.plate_kana = request.form.get("plate_kana")
        vehicle.plate_number = request.form.get("plate_number")
        vehicle.type = request.form.get("type")
        vehicle.office = request.form.get("office")
        vehicle.inspection_expiry = request.form.get("inspection_expiry")

        db.session.commit()

        return redirect("/master/vehicles")

    vehicle_dict = {
        "vehicle_id": vehicle.vehicle_id,
        "plate_area": vehicle.plate_area,
        "plate_class": vehicle.plate_class,
        "plate_kana": vehicle.plate_kana,
        "plate_number": vehicle.plate_number,
        "number": vehicle_number({
            "plate_area": vehicle.plate_area,
            "plate_class": vehicle.plate_class,
            "plate_kana": vehicle.plate_kana,
            "plate_number": vehicle.plate_number,
        }),
        "type": vehicle.type,
        "office": vehicle.office,
        "inspection_expiry": vehicle.inspection_expiry,
    }

    return render_template(
        "vehicle_form.html",
        vehicle=vehicle_dict,
        index=vehicle.id,
        offices=offices_for_current_company(),
        vehicle_types=vehicle_types_for_current_company(),
        mode="edit"
    )

@app.route("/master/vehicles/<int:index>/delete", methods=["POST"])
def delete_vehicle(index):
    vehicle = Vehicle.query.get(index)

    if not vehicle:
        return redirect("/master/vehicles")

    if session.get("role") != "itc":
        if vehicle.company_code != session.get("company_code"):
            return redirect("/master/vehicles")

    vehicle_id = vehicle.vehicle_id

    for driver in Driver.query.filter_by(
        company_code=vehicle.company_code
    ).all():
        vehicles = json.loads(driver.vehicles_json or "[]")

        if vehicle_id in vehicles:
            vehicles.remove(vehicle_id)
            driver.vehicles_json = json.dumps(
                vehicles,
                ensure_ascii=False
            )

    for user in User.query.filter_by(
        company_code=vehicle.company_code
    ).all():
        favorite_vehicles = json.loads(user.favorite_vehicles_json or "[]")

        if vehicle_id in favorite_vehicles:
            favorite_vehicles.remove(vehicle_id)
            user.favorite_vehicles_json = json.dumps(
                favorite_vehicles,
                ensure_ascii=False
            )

    vehicle.deleted = True
    db.session.commit()

    return redirect("/master/vehicles")

@app.route("/master/manuals")
def manual_master():
    return render_template(
        "manual_master.html",
        manuals=manuals_for_current_company()
    )

@app.route("/master/manuals/new", methods=["GET", "POST"])
def new_manual():
    if request.method == "POST":
        file = request.files.get("file")

        filename = ""
        if file and file.filename:
            filename = secure_filename(file.filename)
            save_path = os.path.join("static/manuals", filename)
            file.save(save_path)

        manual = Manual(
            company_code=session.get("company_code"),
            title=request.form.get("title"),
            category=request.form.get("category"),
            filename=filename
        )

        db.session.add(manual)
        db.session.commit()

        return redirect("/master/manuals")

    return render_template(
        "manual_form.html",
        manual=None,
        index=None,
        mode="new"
    )

@app.route("/master/manuals/<int:index>/edit", methods=["GET", "POST"])
def edit_manual(index):
    manual = Manual.query.get(index)

    if not manual:
        return redirect("/master/manuals")

    if session.get("role") != "itc":
        if manual.company_code != session.get("company_code"):
            return redirect("/master/manuals")

    if request.method == "POST":
        manual.title = request.form.get("title")
        manual.category = request.form.get("category")

        file = request.files.get("file")
        if file and file.filename:
            filename = secure_filename(file.filename)
            save_path = os.path.join("static/manuals", filename)
            file.save(save_path)
            manual.filename = filename

        db.session.commit()

        return redirect("/master/manuals")

    manual_dict = {
        "id": manual.id,
        "index": manual.id,
        "company_code": manual.company_code,
        "title": manual.title,
        "category": manual.category,
        "filename": manual.filename,
    }

    return render_template(
        "manual_form.html",
        manual=manual_dict,
        index=manual.id,
        mode="edit"
    )

@app.route("/master/manuals/<int:index>/delete", methods=["POST"])
def delete_manual(index):
    manual = Manual.query.get(index)

    if not manual:
        return redirect("/master/manuals")

    if session.get("role") != "itc":
        if manual.company_code != session.get("company_code"):
            return redirect("/master/manuals")

    db.session.delete(manual)
    db.session.commit()

    return redirect("/master/manuals")

@app.route("/master/checklists")
def checklist_master():
    return render_template(
        "checklist_master.html",
        checklists=checklists_for_current_company()
    )

@app.route("/master/checklists/new", methods=["GET", "POST"])
def new_checklist():
    if request.method == "POST":
        item_categories = request.form.getlist("item_category")
        item_contents = request.form.getlist("item_content")
        input_types = request.form.getlist("input_type")
        item_types = request.form.getlist("item_type")
        approval_labels = request.form.getlist("approval_label")
        choices_list = request.form.getlist("choices")
        criteria_list = request.form.getlist("criteria")
        comment_required_list = request.form.getlist("comment_required")

        items = []

        for i in range(len(item_types)):
            item_type = item_types[i]

            if item_type == "approval":
                label = ""

                if i < len(approval_labels):
                    label = approval_labels[i]

                items.append({
                    "item_type": "approval",
                    "approval_label": label,
                    "criteria_files": [],
                })

                continue

            if i >= len(item_contents):
                continue

            if not item_contents[i]:
                continue

            choices = []

            if input_types[i] == "select":
                choices = [
                    choice.strip()
                    for choice in choices_list[i].split(",")
                    if choice.strip()
                ]

            criteria_files = []

            for file in request.files.getlist(f"criteria_files_{i}"):
                if file.filename:
                    filename = secure_filename(file.filename)
                    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                    file.save(save_path)
                    criteria_files.append(filename)

            items.append({
                "item_type": "check",
                "category": item_categories[i],
                "content": item_contents[i],
                "input_type": input_types[i],
                "choices": choices,
                "criteria": criteria_list[i],
                "criteria_files": criteria_files,
                "comment_required": str(i) in comment_required_list,
            })

        frequency_value = ""
        frequency_unit = ""
        display_type = ""

        if request.form.get("target") == "車両管理":
            frequency_value = request.form.get("frequency_value")
            frequency_unit = request.form.get("frequency_unit")
            display_type = request.form.get("display_type")

        checklist = Checklist(
            company_code=session.get("company_code"),
            name=request.form.get("name"),
            target=request.form.get("target"),
            frequency_value=frequency_value,
            frequency_unit=frequency_unit,
            display_type=display_type,
            items_json=json.dumps(items, ensure_ascii=False)
        )

        db.session.add(checklist)
        db.session.commit()

        return redirect("/master/checklists")

    return render_template(
        "checklist_form.html",
        checklist=None,
        index=None,
        mode="new"
    )

@app.route("/safety/checklists")
def safety_checklists():
    safety_lists = []

    for checklist in checklists_for_current_company():
        if checklist["target"] == "安全管理":
            safety_lists.append(checklist)

    return render_template(
        "safety_checklists.html",
        checklists=safety_lists
    )

@app.route("/safety/checklists/<int:index>")
def safety_checklist_results(index):
    checklist_record = Checklist.query.get(index)

    if not checklist_record:
        return redirect("/safety/checklists")

    if session.get("role") != "itc":
        if checklist_record.company_code != session.get("company_code"):
            return redirect("/safety/checklists")

    checklist = checklist_to_dict(checklist_record)

    results = []

    query = ChecklistResult.query.filter_by(
        checklist_id=checklist_record.id
    )

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    for result in query.order_by(ChecklistResult.id.desc()).all():
        item = checklist_result_to_dict(result)

        if not can_view_checklist_result(item):
            continue

        item["can_manage"] = can_manage_checklist_result(item)
        results.append(item)

    return render_template(
        "safety_checklist_results.html",
        checklist=checklist,
        checklist_index=checklist_record.id,
        results=results
    )


@app.route("/safety/checklist-results/<int:result_index>")
def checklist_result_detail(result_index):
    result_record = ChecklistResult.query.get(result_index)

    if not result_record:
        return redirect("/safety/checklists")

    result = checklist_result_to_dict(result_record)

    if not can_view_checklist_result(result):
        return redirect("/safety/checklists")

    checklist_record = Checklist.query.get(result_record.checklist_id)

    if not checklist_record:
        return redirect("/safety/checklists")

    checklist = checklist_to_dict(checklist_record)

    criteria_list = []

    for answer in result["answers"]:
        criteria = answer.get("criteria", "")
        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)

    summary = {}

    for answer in result["answers"]:
        value = answer.get("value") or "未入力"

        if value not in summary:
            summary[value] = 0

        summary[value] += 1

    return render_template(
        "checklist_result_detail.html",
        result=result,
        result_index=result_record.id,
        summary=summary,
        criteria_list=criteria_list,
        checklist=checklist,
        can_manage=can_manage_checklist_result(result),
        can_approve=can_approve_checklist_result(result),
    )

@app.route("/safety/checklist-results/<int:result_index>/edit", methods=["GET", "POST"])
def edit_checklist_result(result_index):
    result_record = ChecklistResult.query.get(result_index)

    if not result_record:
        return redirect("/safety/checklists")

    result = checklist_result_to_dict(result_record)

    if not can_manage_checklist_result(result):
        return redirect(f"/safety/checklist-results/{result_index}")

    checklist_record = Checklist.query.get(result_record.checklist_id)

    if not checklist_record:
        return redirect("/safety/checklists")

    checklist = checklist_to_dict(checklist_record)

    if request.method == "POST":
        answers = []
        answer_index = 0

        for item in checklist["items"]:
            if item.get("item_type") == "approval":
                continue

            answers.append({
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "criteria": item.get("criteria", ""),
                "criteria_files": item.get("criteria_files", []),
                "value": request.form.get(f"answer_{answer_index}"),
                "comment": request.form.get(f"comment_{answer_index}"),
                "files": result["answers"][answer_index].get("files", []) if answer_index < len(result["answers"]) else [],
                "patrol_link": False,
            })

            answer_index += 1

        result_record.target_type = request.form.get("target_type")
        result_record.target_user = request.form.get("target_user")
        result_record.target_vehicle = request.form.get("target_vehicle")
        result_record.target_office = request.form.get("target_office")
        result_record.answers_json = json.dumps(answers, ensure_ascii=False)

        db.session.commit()

        return redirect(f"/safety/checklist-results/{result_record.id}")

    criteria_list = []

    for item in checklist["items"]:
        criteria = item.get("criteria", "")

        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)

    return render_template(
        "checklist_result_form.html",
        checklist=checklist,
        index=checklist_record.id,
        result=result,
        result_index=result_record.id,
        mode="edit",
        criteria_list=criteria_list,
        drivers=drivers_for_current_company(),
        vehicles=vehicles_with_numbers(),
        offices=offices_for_current_company()
    )

@app.route("/safety/checklist-results/<int:result_index>/delete", methods=["POST"])
def delete_checklist_result(result_index):
    result_record = ChecklistResult.query.get(result_index)

    if not result_record:
        return redirect("/safety/checklists")

    result = checklist_result_to_dict(result_record)

    if not can_manage_checklist_result(result):
        return redirect(f"/safety/checklist-results/{result_index}")

    checklist_id = result_record.checklist_id

    db.session.delete(result_record)
    db.session.commit()

    return redirect(f"/safety/checklists/{checklist_id}")

@app.route("/vehicle/checklists")
def vehicle_checklists():
    vehicle_lists = []

    for checklist in checklists_for_current_company():
        if checklist["target"] == "車両管理":
            vehicle_lists.append(checklist)

    return render_template(
        "vehicle_checklists.html",
        checklists=vehicle_lists
    )

@app.route("/vehicle/checklists/<int:index>")
def vehicle_checklist_results(index):
    checklist_record = Checklist.query.get(index)

    if not checklist_record:
        return redirect("/vehicle/checklists")

    if session.get("role") != "itc":
        if checklist_record.company_code != session.get("company_code"):
            return redirect("/vehicle/checklists")

    checklist = checklist_to_dict(checklist_record)

    if checklist["target"] != "車両管理":
        return redirect("/vehicle/checklists")

    year = request.args.get("year", str(datetime.now().year))
    month = request.args.get("month", str(datetime.now().month).zfill(2))
    vehicle_id = request.args.get("vehicle_id", "")

    if checklist.get("frequency_unit") == "year":
        default_active_day = str(datetime.now().year)
    elif checklist.get("display_type") == "month":
        default_active_day = str(datetime.now().day).zfill(2)
    else:
        default_active_day = str(datetime.now().month).zfill(2)

    active_day = request.args.get("active_day", default_active_day)

    if not active_day:
        active_day = datetime.now().strftime("%d")

    display_days = []
    display_weekdays = {}
    week_names = ["月", "火", "水", "木", "金", "土", "日"]

    frequency_unit = checklist.get("frequency_unit", "")
    display_mode = "month"

    if frequency_unit == "year":
        display_mode = "year_list"
        base_year = int(year)

        for y in range(base_year, base_year + 5):
            display_days.append(y)
            display_weekdays[y] = {
                "name": "",
                "is_weekend": False
            }

    elif checklist.get("display_type") == "month":
        display_mode = "day_list"

        import calendar
        last_day = calendar.monthrange(int(year), int(month))[1]

        for day in range(1, last_day + 1):
            display_days.append(day)

            weekday_index = datetime(int(year), int(month), day).weekday()

            display_weekdays[day] = {
                "name": week_names[weekday_index],
                "is_weekend": weekday_index in [5, 6]
            }

    else:
        display_mode = "month_list"

        for m in range(1, 13):
            display_days.append(m)
            display_weekdays[m] = {
                "name": "",
                "is_weekend": False
            }

    results = []

    query = VehicleChecklistResult.query.filter_by(
        checklist_id=checklist_record.id
    )

    if session.get("role") != "itc":
        query = query.filter_by(
            company_code=session.get("company_code")
        )

    if vehicle_id:
        query = query.filter_by(
            vehicle_id=vehicle_id
        )

    for result_record in query.all():
        result = vehicle_checklist_result_to_dict(result_record)

        if display_mode == "year_list":
            if int(result.get("year", 0)) not in [int(d) for d in display_days]:
                continue

        elif display_mode == "month_list":
            if str(result.get("year")) != str(year):
                continue

        else:
            if str(result.get("year")) != str(year):
                continue

            if str(result.get("month")).zfill(2) != str(month).zfill(2):
                continue

        results.append(result)

    return render_template(
        "vehicle_checklist_results.html",
        checklist=checklist,
        checklist_index=checklist_record.id,
        results=results,
        vehicles=vehicles_with_numbers(),
        year=year,
        month=month,
        vehicle_id=vehicle_id,
        active_day=active_day,
        display_days=display_days,
        display_weekdays=display_weekdays,
        display_mode=display_mode,
        can_approve=session.get("role") in ["admin", "itc"]
    )


@app.route("/vehicle/checklist-results/<int:result_index>/approve", methods=["POST"])
def approve_vehicle_checklist_result(result_index):
    result_record = VehicleChecklistResult.query.get(result_index)

    if not result_record:
        return redirect("/vehicle/checklists")

    if session.get("role") not in ["admin", "itc"]:
        return redirect("/vehicle/checklists")

    if session.get("role") != "itc":
        if result_record.company_code != session.get("company_code"):
            return redirect("/vehicle/checklists")

    if result_record.status == "承認済み":
        result_record.status = "承認待ち"
        result_record.approved_by = ""
        result_record.approved_date = ""
    else:
        result_record.status = "承認済み"
        result_record.approved_by = session.get("name")
        result_record.approved_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    db.session.commit()

    checklist_record = Checklist.query.get(result_record.checklist_id)

    if checklist_record:
        checklist = checklist_to_dict(checklist_record)

        if checklist.get("frequency_unit") == "year":
            active_value = result_record.year
        else:
            active_value = result_record.day
    else:
        active_value = result_record.day

    return redirect(
        f"/vehicle/checklists/{result_record.checklist_id}"
        f"?vehicle_id={result_record.vehicle_id}"
        f"&year={result_record.year}"
        f"&month={result_record.month}"
        f"&active_day={active_value}"
    )

@app.route("/vehicle/checklists/<int:index>/save-one", methods=["POST"])
def save_vehicle_checklist_one(index):
    checklist_record = Checklist.query.get(index)

    if not checklist_record:
        return redirect("/vehicle/checklists")

    if session.get("role") != "itc":
        if checklist_record.company_code != session.get("company_code"):
            return redirect("/vehicle/checklists")

    checklist = checklist_to_dict(checklist_record)

    vehicle_id = request.form.get("vehicle_id")
    year = request.form.get("year", "")
    month = request.form.get("month", "")
    day = request.form.get("day", "")

    if checklist.get("frequency_unit") == "year":
        month = "01"
        day = "01"
    elif checklist.get("display_type") == "month":
        month = str(month).zfill(2)
        day = str(day).zfill(2)
    else:
        month = str(month).zfill(2)
        day = "01"

    active_day = request.form.get("active_day")

    item_no = request.form.get("item_no")
    category = request.form.get("category")
    content = request.form.get("content")
    criteria = request.form.get("criteria")
    value = request.form.get("value")

    result_record = VehicleChecklistResult.query.filter_by(
        checklist_id=checklist_record.id,
        vehicle_id=vehicle_id,
        year=year,
        month=month,
        day=day
    ).first()

    if not result_record:
        result_record = VehicleChecklistResult(
            company_code=session.get("company_code"),
            checklist_id=checklist_record.id,
            vehicle_id=vehicle_id,
            year=year,
            month=month,
            day=day,
            checked_by=session.get("name"),
            checked_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            status="承認待ち",
            approved_by="",
            approved_date="",
            reject_reason="",
            answers_json="[]"
        )

        db.session.add(result_record)

    answers = json.loads(result_record.answers_json or "[]")

    answer = None

    for a in answers:
        if str(a.get("item_no", "")) == str(item_no):
            answer = a
            break

    if not answer:
        answer = {
            "item_no": item_no,
            "category": category,
            "content": content,
            "criteria": criteria,
            "value": "",
            "comment": "",
            "files": []
        }
        answers.append(answer)

    answer["value"] = value
    answer["category"] = category
    answer["content"] = content
    answer["criteria"] = criteria

    result_record.checked_by = session.get("name")
    result_record.checked_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    result_record.status = "承認待ち"
    result_record.approved_by = ""
    result_record.approved_date = ""
    result_record.answers_json = json.dumps(answers, ensure_ascii=False)

    db.session.commit()

    return redirect(
        f"/vehicle/checklists/{checklist_record.id}?vehicle_id={vehicle_id}&year={year}&month={month}&active_day={active_day}"
    )

@app.route("/vehicle/checklists/<int:index>/save-detail", methods=["POST"])
def save_vehicle_checklist_detail(index):
    checklist_record = Checklist.query.get(index)

    if not checklist_record:
        return redirect("/vehicle/checklists")

    if session.get("role") != "itc":
        if checklist_record.company_code != session.get("company_code"):
            return redirect("/vehicle/checklists")

    checklist = checklist_to_dict(checklist_record)

    vehicle_id = request.form.get("vehicle_id")
    year = request.form.get("year", "")
    month = request.form.get("month", "")
    day = request.form.get("day", "")

    if checklist.get("frequency_unit") == "year":
        month = "01"
        day = "01"
    elif checklist.get("display_type") == "month":
        month = str(month).zfill(2)
        day = str(day).zfill(2)
    else:
        month = str(month).zfill(2)
        day = "01"

    content = request.form.get("content")
    item_no = request.form.get("item_no")
    active_day = request.form.get("active_day")
    category = request.form.get("category")
    criteria = request.form.get("criteria")
    comment = request.form.get("comment")

    result_record = VehicleChecklistResult.query.filter_by(
        checklist_id=checklist_record.id,
        vehicle_id=vehicle_id,
        year=year,
        month=month,
        day=day
    ).first()

    if not result_record:
        result_record = VehicleChecklistResult(
            company_code=session.get("company_code"),
            checklist_id=checklist_record.id,
            vehicle_id=vehicle_id,
            year=year,
            month=month,
            day=day,
            checked_by=session.get("name"),
            checked_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            status="承認待ち",
            approved_by="",
            approved_date="",
            reject_reason="",
            answers_json="[]"
        )
        db.session.add(result_record)

    answers = json.loads(result_record.answers_json or "[]")

    answer = None

    for a in answers:
        if str(a.get("item_no", "")) == str(item_no):
            answer = a
            break

    if not answer:
        answer = {
            "category": category,
            "item_no": item_no,
            "content": content,
            "criteria": criteria,
            "value": "",
            "comment": "",
            "files": []
        }
        answers.append(answer)

    uploaded_files = request.files.getlist("files")
    answer.setdefault("files", [])

    for file in uploaded_files:
        if file.filename:
            filename = secure_filename(file.filename)
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_path)
            answer["files"].append(filename)

    answer["comment"] = comment
    answer["category"] = category
    answer["content"] = content
    answer["criteria"] = criteria

    result_record.checked_by = session.get("name")
    result_record.checked_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    result_record.status = "承認待ち"
    result_record.approved_by = ""
    result_record.approved_date = ""
    result_record.answers_json = json.dumps(answers, ensure_ascii=False)

    if request.form.get("patrol_link") == "1":
        db.session.add(VehiclePatrol(
            company_code=session.get("company_code"),
            vehicle_id=vehicle_id,
            occurred_date=f"{year}-{month}-{day}",
            category="点検指摘",
            priority="中",
            content=content,
            cause="",
            temporary_action=comment,
            repair_content="",
            status="未対応",
            repair_date="",
            repair_person="",
            repair_time="",
            parts="",
            cost=""
        ))

    notify_mentions(
        comment,
        f"/vehicle/checklists/{checklist_record.id}?vehicle_id={vehicle_id}&year={year}&month={month}&active_day={active_day}"
    )

    db.session.commit()

    return redirect(
        f"/vehicle/checklists/{checklist_record.id}?vehicle_id={vehicle_id}&year={year}&month={month}&active_day={active_day}"
    )

@app.route("/vehicle/checklists/<int:index>/new", methods=["GET", "POST"])
def new_vehicle_checklist_result(index):
    checklist_record = Checklist.query.get(index)

    if not checklist_record:
        return redirect("/vehicle/checklists")

    if session.get("role") != "itc":
        if checklist_record.company_code != session.get("company_code"):
            return redirect("/vehicle/checklists")

    checklist = checklist_to_dict(checklist_record)

    if checklist["target"] != "車両管理":
        return redirect("/vehicle/checklists")

    if request.method == "POST":
        vehicle_id = request.form.get("vehicle_id")
        year = request.form.get("year")
        month = request.form.get("month")
        day = request.form.get("day")

        answers = []
        answer_index = 0

        for item in checklist["items"]:
            if item.get("item_type") == "approval":
                continue

            file_names = []

            uploaded_files = request.files.getlist(f"files_{answer_index}")

            for file in uploaded_files:
                if file.filename:
                    filename = secure_filename(file.filename)
                    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                    file.save(save_path)
                    file_names.append(filename)

            answers.append({
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "criteria": item.get("criteria", ""),
                "value": request.form.get(f"answer_{answer_index}"),
                "comment": request.form.get(f"comment_{answer_index}"),
                "files": file_names
            })

            answer_index += 1

        result = VehicleChecklistResult(
            company_code=session.get("company_code"),
            checklist_id=checklist_record.id,
            vehicle_id=vehicle_id,
            year=year,
            month=str(month).zfill(2),
            day=str(day).zfill(2),
            checked_by=session.get("name"),
            checked_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            status="承認待ち",
            approved_by="",
            approved_date="",
            reject_reason="",
            answers_json=json.dumps(answers, ensure_ascii=False)
        )

        db.session.add(result)
        db.session.commit()

        return redirect(
            f"/vehicle/checklists/{checklist_record.id}?vehicle_id={vehicle_id}&year={year}&month={str(month).zfill(2)}"
        )

    return render_template(
        "vehicle_checklist_form.html",
        checklist=checklist,
        checklist_index=checklist_record.id,
        vehicles=vehicles_with_numbers(),
        mode="new",
        now_year=datetime.now().year,
        now_month=datetime.now().month,
        now_day=datetime.now().day
    )

@app.route("/safety/checklists/<int:index>/new", methods=["GET", "POST"])
def new_safety_checklist_result(index):
    checklist_record = Checklist.query.get(index)

    if not checklist_record:
        return redirect("/safety/checklists")

    if session.get("role") != "itc":
        if checklist_record.company_code != session.get("company_code"):
            return redirect("/safety/checklists")

    checklist = checklist_to_dict(checklist_record)

    if request.method == "POST":
        answers = []
        answer_index = 0

        for item in checklist["items"]:
            if item.get("item_type") == "approval":
                continue

            value = request.form.get(f"answer_{answer_index}")
            comment = request.form.get(f"comment_{answer_index}")
            patrol_link = request.form.get(f"patrol_link_{answer_index}")

            file_names = []

            uploaded_files = request.files.getlist(f"files_{answer_index}")

            for file in uploaded_files:
                if file.filename:
                    filename = secure_filename(file.filename)
                    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                    file.save(save_path)
                    file_names.append(filename)

            answers.append({
                "category": item.get("category", ""),
                "content": item.get("content", ""),
                "criteria": item.get("criteria", ""),
                "criteria_files": item.get("criteria_files", []),
                "value": value,
                "comment": comment,
                "files": file_names,
                "patrol_link": patrol_link == "1",
            })

            if patrol_link == "1":
                db.session.add(PatrolResult(
                    company_code=session.get("company_code"),
                    created_by_username=session.get("username"),
                    created_by_name=session.get("name"),
                    date=datetime.now().strftime("%Y-%m-%d"),
                    office=session.get("office"),
                    delivery_place="",
                    category="点検指摘",
                    content_type="安全",
                    target_type=request.form.get("target_type") or "user",
                    target_user=request.form.get("target_user") or session.get("name"),
                    content=(
                        f"{item.get('category', '')}：{item.get('content', '')}"
                        f" / 評価：{value or '-'}"
                        f" / コメント：{comment or '-'}"
                    ),
                    files_json=json.dumps(file_names, ensure_ascii=False),
                    countermeasure="",
                    approval_status="未対応",
                    reject_reason=""
                ))

            answer_index += 1

        result = ChecklistResult(
            company_code=session.get("company_code"),
            checklist_id=checklist_record.id,
            target_type=request.form.get("target_type"),
            target_user=request.form.get("target_user"),
            target_vehicle=request.form.get("target_vehicle"),
            target_office=request.form.get("target_office"),
            checked_by=session.get("name"),
            checked_date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            approved_by="",
            approved_date="",
            reject_reason="",
            status="承認待ち",
            answers_json=json.dumps(answers, ensure_ascii=False)
        )

        db.session.add(result)
        db.session.commit()

        return redirect(f"/safety/checklists/{checklist_record.id}")

    criteria_list = []

    for item in checklist["items"]:
        if item.get("item_type") == "approval":
            continue

        criteria = item.get("criteria", "")
        if criteria and criteria not in criteria_list:
            criteria_list.append(criteria)

    return render_template(
        "checklist_result_form.html",
        checklist=checklist,
        index=checklist_record.id,
        criteria_list=criteria_list,
        drivers=drivers_for_current_company(),
        vehicles=vehicles_with_numbers(),
        offices=offices_for_current_company()
    )

@app.route("/master/checklists/<int:index>/edit", methods=["GET", "POST"])
def edit_checklist(index):
    checklist_record = Checklist.query.get(index)

    if not checklist_record:
        return redirect("/master/checklists")

    if session.get("role") != "itc":
        if checklist_record.company_code != session.get("company_code"):
            return redirect("/master/checklists")

    checklist = checklist_to_dict(checklist_record)

    if request.method == "POST":
        item_categories = request.form.getlist("item_category")
        item_contents = request.form.getlist("item_content")
        input_types = request.form.getlist("input_type")
        item_types = request.form.getlist("item_type")
        approval_labels = request.form.getlist("approval_label")
        choices_list = request.form.getlist("choices")
        criteria_list = request.form.getlist("criteria")
        comment_required_list = request.form.getlist("comment_required")

        old_items = checklist.get("items", [])
        items = []

        for i in range(len(item_types)):
            item_type = item_types[i]

            if item_type == "approval":
                label = ""

                if i < len(approval_labels):
                    label = approval_labels[i]

                items.append({
                    "item_type": "approval",
                    "approval_label": label,
                    "criteria_files": [],
                })

                continue

            if i >= len(item_contents):
                continue

            if not item_contents[i]:
                continue

            choices = []

            if input_types[i] == "select":
                choices = [
                    choice.strip()
                    for choice in choices_list[i].split(",")
                    if choice.strip()
                ]

            criteria_files = []

            if i < len(old_items):
                criteria_files = list(old_items[i].get("criteria_files", []))

            for file in request.files.getlist(f"criteria_files_{i}"):
                if file.filename:
                    filename = secure_filename(file.filename)
                    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                    file.save(save_path)
                    criteria_files.append(filename)

            items.append({
                "item_type": "check",
                "category": item_categories[i],
                "content": item_contents[i],
                "input_type": input_types[i],
                "choices": choices,
                "criteria": criteria_list[i],
                "criteria_files": criteria_files,
                "comment_required": str(i) in comment_required_list,
            })

        checklist_record.name = request.form.get("name")
        checklist_record.target = request.form.get("target")

        if request.form.get("target") == "車両管理":
            checklist_record.frequency_value = request.form.get("frequency_value")
            checklist_record.frequency_unit = request.form.get("frequency_unit")
            checklist_record.display_type = request.form.get("display_type")
        else:
            checklist_record.frequency_value = ""
            checklist_record.frequency_unit = ""
            checklist_record.display_type = ""

        checklist_record.items_json = json.dumps(items, ensure_ascii=False)

        db.session.commit()

        return redirect("/master/checklists")

    return render_template(
        "checklist_form.html",
        checklist=checklist,
        index=checklist_record.id,
        mode="edit"
    )


@app.route("/master/checklists/<int:index>/delete", methods=["POST"])
def delete_checklist(index):
    checklist = Checklist.query.get(index)

    if not checklist:
        return redirect("/master/checklists")

    if session.get("role") != "itc":
        if checklist.company_code != session.get("company_code"):
            return redirect("/master/checklists")

    db.session.delete(checklist)
    db.session.commit()

    return redirect("/master/checklists")


@app.route("/safety/checklist-results/<int:result_index>/approve", methods=["POST"])
def approve_checklist_result(result_index):
    result_record = ChecklistResult.query.get(result_index)

    if not result_record:
        return redirect("/safety/checklists")

    result = checklist_result_to_dict(result_record)

    if not can_approve_checklist_result(result):
        return redirect(f"/safety/checklist-results/{result_index}")

    result_record.status = "承認済み"
    result_record.approved_by = session.get("name")
    result_record.approved_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    result_record.reject_reason = ""

    db.session.commit()

    return redirect(f"/safety/checklist-results/{result_record.id}")

@app.route("/safety/checklist-results/<int:result_index>/reject", methods=["POST"])
def reject_checklist_result(result_index):
    result_record = ChecklistResult.query.get(result_index)

    if not result_record:
        return redirect("/safety/checklists")

    result = checklist_result_to_dict(result_record)

    if not can_approve_checklist_result(result):
        return redirect(f"/safety/checklist-results/{result_index}")

    reject_reason = request.form.get("reject_reason", "")

    result_record.status = "差し戻し"
    result_record.approved_by = session.get("name")
    result_record.approved_date = ""
    result_record.reject_reason = reject_reason

    notify_users = set()

    if result_record.checked_by:
        notify_users.add(result_record.checked_by)

    if result_record.target_user:
        notify_users.add(result_record.target_user)

    for target_user in notify_users:
        add_notification(
            target_user,
            "チェックリストが差し戻されました",
            reject_reason or "チェックリストが差し戻されました。",
            f"/safety/checklist-results/{result_record.id}"
        )

    db.session.commit()

    return redirect(f"/safety/checklist-results/{result_record.id}")

def init_db():
    with app.app_context():
        db.create_all()

        if not Company.query.filter_by(company_code="ITC").first():
            db.session.add(Company(
                company_code="ITC",
                company_name="ITC",
                vehicle_limit=9999,
                active=True
            ))

        if not User.query.filter_by(company_code="ITC", username="itc").first():
            db.session.add(User(
                company_code="ITC",
                username="itc",
                password=generate_password_hash("itc123"),
                role="itc",
                name="ITC管理者",
                office="ITC",
                favorite_vehicles_json="[]"
            ))

        db.session.commit()


init_db()


if __name__ == "__main__":
    app.run(debug=False)