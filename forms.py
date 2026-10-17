from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, FloatField, DateField, SelectField
from wtforms.validators import DataRequired, EqualTo

class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    confirm_password = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo('password', message="Passwords must match")])
    submit = SubmitField("Register")

class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class AddFriendForm(FlaskForm):
    username = StringField("Friend's Username", validators=[DataRequired()])
    submit = SubmitField("Send Friend Request")

class LoanRequestForm(FlaskForm):
    # We will populate choices dynamically in app.py based on their actual friends list
    friend_id = SelectField("Lender (Friend)", choices=[], validators=[DataRequired()])
    amount = FloatField("Amount to Borrow", validators=[DataRequired()])
    interest_rate = FloatField("Interest Rate (%)", validators=[DataRequired()])
    due_date = DateField("Due Date (YYYY-MM-DD)", format='%Y-%m-%d', validators=[DataRequired()])
    submit = SubmitField("Send Loan Request")