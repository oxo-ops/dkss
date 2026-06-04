from flask import Flask, render_template, request, redirect, session

app = Flask(__name__)
app.secret_key = "dev_secret_key"

USERS = [
    {"company_code": "ITC", "username": "itc", "password": "itc123", "role": "itc"},
    {"company_code": "AAA", "username": "admin", "password": "admin123", "role": "admin"},
    {"company_code": "AAA", "username": "user01", "password": "user123", "role": "user"},
    {"company_code": "BBB", "username": "admin", "password": "admin123", "role": "admin"},
    {"company_code": "BBB", "username": "user01", "password": "user123", "role": "user"},
]

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        company_code = request.form.get("company_code")
        username = request.form.get("username")
        password = request.form.get("password")

        for user in USERS:
            if (
                user["company_code"] == company_code
                and user["username"] == username
                and user["password"] == password
            ):
                session["company_code"] = user["company_code"]
                session["username"] = user["username"]
                session["role"] = user["role"]

                if user["role"] == "itc":
                    return redirect("/itc")
                return redirect("/")

        error = "会社コード、ユーザーID、またはパスワードが違います。"

    return render_template("login.html", error=error)

@app.route("/")
def dashboard():
    return render_template("index.html")

@app.route("/itc")
def itc_dashboard():
    return render_template("itc_dashboard.html")

if __name__ == "__main__":
    app.run(debug=True)
@app.route("/safety")
def safety():
    return render_template("safety.html")

@app.route("/analysis")
def analysis():
    return render_template("analysis.html")

@app.route("/manuals")
def manuals():
    return render_template("manuals.html")