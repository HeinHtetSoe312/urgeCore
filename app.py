from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_session import Session
from forms import RegisterForm, LoginForm, AddFriendForm, LoanRequestForm
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db, close_db
from datetime import datetime

app = Flask(__name__)
app.config["SECRET_KEY"] = "a-very-nice-secret-key"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

app.teardown_appcontext(close_db)

@app.route("/")
def index():
    # If the user is logged in, send them to their dashboard
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        db = get_db()
        username = form.username.data
        password = form.password.data

        # Check if user already exists
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user:
            flash("Username already exists. Please choose another.")
            return render_template("register.html", form=form)

        # Hash password and save to DB
        hashed_pw = generate_password_hash(password)
        
        # We capture the cursor so we can grab the new user's generated ID
        cursor = db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", 
                   (username, hashed_pw))
        db.commit()
        
        # --- THE AUTO-LOGIN MAGIC ---
        session["user_id"] = cursor.lastrowid
        session["username"] = username
        
        flash("Registration successful! Welcome to the network.")
        return redirect(url_for("dashboard"))

    return render_template("register.html", form=form)

@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        db = get_db()
        username = form.username.data
        password = form.password.data

        # Fetch user from DB
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        # Verify user exists and password matches
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.")

    return render_template("login.html", form=form)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        flash("Login first.")
        return redirect(url_for("login"))
    
    db = get_db()
    user_id = session["user_id"]

    # 1. Fetch the ENTIRE user row, not just the balance
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    # If the user doesn't exist in the database anymore, clear their session and force login
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    # Calculate total debt and total lended (for the UI cards)
    total_debt_row = db.execute("""SELECT SUM(amount) as total 
                                FROM loans 
                                WHERE borrower_id = ? AND status = 'accepted'""", (user_id,)).fetchone()
    
    total_debt = total_debt_row["total"] if total_debt_row["total"] else 0.0

    total_lended_row = db.execute("""SELECT SUM(amount) as total
                                  FROM loans
                                  WHERE lender_id = ? AND status = 'accepted'""", (user_id,)).fetchone()
    
    total_lended = total_lended_row["total"] if total_lended_row["total"] else 0.0

    pending_friends = db.execute("""
        SELECT f.id as request_id, u.username 
        FROM friendships f JOIN users u ON f.user_id = u.id
        WHERE f.friend_id = ? AND f.status = 'pending'
    """, (user_id,)).fetchall()

    pending_loans = db.execute("""
        SELECT l.id as loan_id, u.username as borrower, l.amount, l.interest_rate, l.due_date, l.status
        FROM loans l JOIN users u ON l.borrower_id = u.id
        WHERE l.lender_id = ? AND (l.status = 'pending' OR l.status = 'countered_by_borrower')
    """, (user_id,)).fetchall()

    borrower_counters = db.execute("""
        SELECT l.id as loan_id, u.username as lender, l.amount, l.interest_rate, l.due_date
        FROM loans l
        JOIN users u ON l.lender_id = u.id
        WHERE l.borrower_id = ? AND l.status = 'countered_by_lender'
    """, (user_id,)).fetchall()

    return render_template("dashboard.html", user=user, total_debt=total_debt, total_lended=total_lended, pending_friends=pending_friends, pending_loans=pending_loans, borrower_counters=borrower_counters)


@app.route("/handle_loan/<int:loan_id>/<action>")
def handle_loan(loan_id, action):
    if not session.get("user_id"):
        flash("Login first.")
        return redirect(url_for("login"))
        
    db = get_db()
    user_id = session["user_id"]
    
    loan = db.execute("SELECT * FROM loans WHERE id = ? AND lender_id = ?", (loan_id, user_id)).fetchone()
    if not loan:
        flash("Loan not found.")
        return redirect(url_for("dashboard"))

    if action == 'accept':
        lender = db.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
        if lender["balance"] < loan["amount"]:
            flash("Insufficient funds to lend this amount!")
        else:
            # Transfer money: Deduct from lender, add to borrower
            db.execute("""UPDATE users SET balance = balance - ? 
                       WHERE id = ?""", (loan["amount"], user_id))
            
            db.execute("""UPDATE users SET balance = balance + ?
                       WHERE id = ?""", (loan["amount"], loan["borrower_id"]))
            
            db.execute("""UPDATE loans SET status = 'accepted' 
                       WHERE id = ?""", (loan_id,))
            flash("Loan accepted! Funds transferred.")
            
    elif action == 'reject':
        db.execute("UPDATE loans SET status = 'rejected' WHERE id = ?", (loan_id,))
        flash("Loan order rejected.")
        
    db.commit()
    return redirect(url_for("dashboard"))


@app.route("/repay_loan/<int:loan_id>")
def repay_loan(loan_id):
    if not session.get("user_id"):
        flash("Login first.")
        return redirect(url_for("login"))
        
    db = get_db()
    user_id = session["user_id"]
    
    loan = db.execute("SELECT * FROM loans WHERE id = ? AND borrower_id = ? AND status = 'accepted'", (loan_id, user_id)).fetchone()
    if not loan:
        flash("Active loan not found.")
        return redirect(url_for("active_loans"))

    # For MVP, we are just repaying the principal amount to keep the math clean.
    amount_due = loan["amount"] 
    
    borrower = db.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
    
    if borrower["balance"] < amount_due:
        flash("Insufficient funds in your wallet to repay this loan.")
    else:
        # Transfer money back
        db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount_due, user_id))
        db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount_due, loan["lender_id"]))
        db.execute("UPDATE loans SET status = 'paid' WHERE id = ?", (loan_id,))
        db.commit()
        flash("Loan fully repaid!")
        
    return redirect(url_for("active_loans"))


@app.route("/handle_friend/<int:req_id>/<action>")
def handle_friend(req_id, action):
    if not session.get("user_id"):
        flash("Login first.")
        return redirect(url_for("login"))
        
    db = get_db()
    
    # We verify friend_id = session['user_id'] so users can't accept requests meant for others
    if action == 'accept':
        db.execute("UPDATE friendships SET status = 'accepted' WHERE id = ? AND friend_id = ?", (req_id, session["user_id"]))
        flash("Friend request accepted!")
    elif action == 'reject':
        db.execute("DELETE FROM friendships WHERE id = ? AND friend_id = ?", (req_id, session["user_id"]))
        flash("Friend request rejected.")
        
    db.commit()
    return redirect(url_for("dashboard"))


@app.route("/add_friend", methods=["GET", "POST"])
def add_friend():
    if not session.get("user_id"):
        flash("Login first.")
        return redirect(url_for("login"))
        
    form = AddFriendForm()
    if form.validate_on_submit():
        db = get_db()
        friend_username = form.username.data
        
        # Find the friend in the database
        friend = db.execute("SELECT * FROM users WHERE username = ?", (friend_username,)).fetchone()
        
        if not friend:
            flash("User not found.")
        elif friend["id"] == session["user_id"]:
            flash("You cannot add yourself, dummy.")
        else:
            # Check if friendship already exists
            existing = db.execute("""
                SELECT * FROM friendships 
                WHERE (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)
            """, (session["user_id"], friend["id"], friend["id"], session["user_id"])).fetchone()
            
            if existing:
                flash("You are already friends or have a pending request.")
            else:
                db.execute("INSERT INTO friendships (user_id, friend_id, status) VALUES (?, ?, 'pending')", 
                           (session["user_id"], friend["id"]))
                db.commit()
                flash("Friend request sent!")
                return redirect(url_for("dashboard"))
                
    return render_template("add_friend.html", form=form)

@app.route("/request_loan", methods=["GET", "POST"])
def request_loan():
    if not session.get("user_id"):
        flash("Login first.")
        return redirect(url_for("login"))
        
    db = get_db()
    form = LoanRequestForm()
    
    # Get all ACCEPTED friends for the dropdown list
    # This SQL query checks both sides of the friendship table to find their friends
    friends_query = """
        SELECT u.id, u.username FROM users u
        JOIN friendships f ON (u.id = f.friend_id OR u.id = f.user_id)
        WHERE (f.user_id = ? OR f.friend_id = ?) AND u.id != ? AND f.status = 'accepted'
    """
    friends = db.execute(friends_query, (session["user_id"], session["user_id"], session["user_id"])).fetchall()
    
    # Populate the WTForms SelectField choices dynamically
    form.friend_id.choices = [(str(f["id"]), f["username"]) for f in friends]
    
    if form.validate_on_submit():
        friend_id = form.friend_id.data
        amount = form.amount.data
        rate = form.interest_rate.data
        due_date = form.due_date.data

        # Insert the pending loan order
        db.execute("""
            INSERT INTO loans (borrower_id, lender_id, amount, interest_rate, due_date, status) 
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (session["user_id"], friend_id, amount, rate, due_date))
        db.commit()
        
        flash(f"Loan request for ${amount} sent successfully!")
        return redirect(url_for("request_loan"))
        
    return render_template("request_loan.html", form=form)

@app.route("/active_loans")
def active_loans():
    if not session.get("user_id"):
        flash("Login first.")
        return redirect(url_for("login"))
        
    db = get_db()
    user_id = session["user_id"]
    
    # 1. Money you owe (You are the borrower)
    borrowed = db.execute("""
        SELECT l.id, u.username as lender, l.amount, l.interest_rate, l.due_date
        FROM loans l
        JOIN users u ON l.lender_id = u.id
        WHERE l.borrower_id = ? AND l.status = 'accepted'
    """, (user_id,)).fetchall()
    
    # 2. Money owed to you (You are the lender)
    lended = db.execute("""
        SELECT l.id, u.username as borrower, l.amount, l.interest_rate, l.due_date
        FROM loans l
        JOIN users u ON l.borrower_id = u.id
        WHERE l.lender_id = ? AND l.status = 'accepted'
    """, (user_id,)).fetchall()
    
    return render_template("active_loans.html", borrowed=borrowed, lended=lended)

# ==========================================
# ACTION ROUTES (Accept/Reject Requests)
# ==========================================

@app.route("/accept_friend/<int:request_id>", methods=["POST"])
def accept_friend(request_id):
    if not session.get("user_id"): return redirect(url_for("login"))
    db = get_db()
    
    # Update the friendship status to accepted
    db.execute("UPDATE friendships SET status = 'accepted' WHERE id = ? AND friend_id = ?", 
               (request_id, session["user_id"]))
    db.commit()
    flash("Friend request accepted!")
    return redirect(url_for("dashboard"))

@app.route("/reject_friend/<int:request_id>", methods=["POST"])
def reject_friend(request_id):
    if not session.get("user_id"): return redirect(url_for("login"))
    db = get_db()
    
    # Delete the pending request entirely
    db.execute("DELETE FROM friendships WHERE id = ? AND friend_id = ?", 
               (request_id, session["user_id"]))
    db.commit()
    flash("Friend request declined.")
    return redirect(url_for("dashboard"))

@app.route("/accept_loan/<int:loan_id>", methods=["POST"])
def accept_loan(loan_id):
    if not session.get("user_id"): return redirect(url_for("login"))
    db = get_db()
    
    # Fetch the loan details
    loan = db.execute("SELECT * FROM loans WHERE id = ? AND lender_id = ?", 
                      (loan_id, session["user_id"])).fetchone()
    
    if loan:
        # Check if the lender has enough money
        lender = db.execute("SELECT balance FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        
        if lender["balance"] >= loan["amount"]:
            # Move the money: Deduct from lender, Add to borrower
            db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (loan["amount"], session["user_id"]))
            db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (loan["amount"], loan["borrower_id"]))
            
            # Mark loan as accepted
            db.execute("UPDATE loans SET status = 'accepted' WHERE id = ?", (loan_id,))
            db.commit()
            flash("Loan funded successfully! Money has been transferred.")
        else:
            flash("Insufficient balance to fund this loan.")
            
    return redirect(url_for("dashboard"))

@app.route("/reject_loan/<int:loan_id>", methods=["POST"])
def reject_loan(loan_id):
    if not session.get("user_id"): return redirect(url_for("login"))
    db = get_db()
    
    # Mark the loan as rejected
    db.execute("UPDATE loans SET status = 'rejected' WHERE id = ? AND (lender_id = ? OR borrower_id = ?)", 
               (loan_id, session["user_id"], session["user_id"]))
    db.commit()
    flash("Loan request declined.")
    return redirect(url_for("dashboard"))

# ==========================================
# PAY BACK LOAN ROUTE
# ==========================================
@app.route("/pay_loan/<int:loan_id>", methods=["POST"])
def pay_loan(loan_id):
    if not session.get("user_id"): return redirect(url_for("login"))
    db = get_db()
    user_id = session["user_id"]
    
    # 1. Fetch the loan and the borrower
    loan = db.execute("SELECT * FROM loans WHERE id = ? AND borrower_id = ?", (loan_id, user_id)).fetchone()
    borrower = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    
    if loan and loan["status"] == "accepted":
        # 2. Calculate the TRUE total (Capital + Interest)
        total_payment = loan["amount"] + (loan["amount"] * (loan["interest_rate"] / 100.0))
        
        # 3. Check if they can afford it
        if borrower["balance"] >= total_payment:
            
            # --- START REPUTATION ALGORITHM ---
            today_str = datetime.now().strftime('%Y-%m-%d')
            due_date_str = str(loan["due_date"])
            current_score = borrower["base_credit_score"]
            
            # Alphabetical string comparison for the win
            if today_str <= due_date_str:
                new_score = current_score + 15
                if new_score > 850: new_score = 850
            else:
                new_score = current_score - 15
                if new_score < 300: new_score = 300
            # --- END REPUTATION ALGORITHM ---

            # 4. Move the money (Borrower loses total, Lender gains total)
            db.execute("UPDATE users SET balance = balance - ?, base_credit_score = ? WHERE id = ?", 
                       (total_payment, new_score, user_id))
            db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", 
                       (total_payment, loan["lender_id"]))
            
            # 5. Mark loan as officially paid!
            db.execute("UPDATE loans SET status = 'paid' WHERE id = ?", (loan_id,))
            db.commit()
            
            flash(f"Loan paid successfully! €{total_payment:.2f} was sent. New Reputation Score: {new_score}")
        else:
            flash("You do not have enough balance to pay off this loan with interest.")
            
    return redirect(url_for("active_loans"))

@app.route("/counter_loan/<int:loan_id>", methods=["POST"])
def counter_loan(loan_id):
    if not session.get("user_id"): return redirect(url_for("login"))
    db = get_db()
    user_id = session["user_id"]
    
    # Grab the new rate typed into the HTML form
    new_rate = request.form.get("new_rate")
    
    # Fetch the loan
    loan = db.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    
    if loan:
        # If the LENDER is the one countering...
        if user_id == loan["lender_id"]:
            db.execute("UPDATE loans SET interest_rate = ?, status = 'countered_by_lender' WHERE id = ?", 
                       (new_rate, loan_id))
            flash(f"Counter offer of {new_rate}% sent to borrower.")
            
        # If the BORROWER is the one countering...
        elif user_id == loan["borrower_id"]:
            db.execute("UPDATE loans SET interest_rate = ?, status = 'countered_by_borrower' WHERE id = ?", 
                       (new_rate, loan_id))
            flash(f"Counter offer of {new_rate}% sent to lender.")
            
        db.commit()
        
    return redirect(url_for("dashboard"))

@app.route("/borrower_accept/<int:loan_id>", methods=["POST"])
def borrower_accept(loan_id):
    if not session.get("user_id"): return redirect(url_for("login"))
    db = get_db()
    user_id = session["user_id"]

    # Make sure the loan exists and the user clicking is actually the borrower
    loan = db.execute("SELECT * FROM loans WHERE id = ? AND borrower_id = ?", (loan_id, user_id)).fetchone()
    
    if loan and loan["status"] == "countered_by_lender":
        # Check if the lender STILL has enough money in their balance
        lender = db.execute("SELECT balance FROM users WHERE id = ?", (loan["lender_id"],)).fetchone()
        
        if lender["balance"] >= loan["amount"]:
            # Move the money: Deduct from lender, Add to borrower
            db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (loan["amount"], loan["lender_id"]))
            db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (loan["amount"], user_id))
            
            # Mark the loan as fully active!
            db.execute("UPDATE loans SET status = 'accepted' WHERE id = ?", (loan_id,))
            db.commit()
            
            flash("You accepted the counter-offer! The loan has been funded.")
        else:
            flash("The lender no longer has enough balance to fund this loan.")
            
    return redirect(url_for("dashboard"))