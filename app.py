@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/vehicles/<id>")
def vehicle_detail(id):
    return render_template("vehicle_detail.html")