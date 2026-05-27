from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.String, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=True)
    first_name = db.Column(db.String(120), nullable=True)
    last_name = db.Column(db.String(120), nullable=True)
    profile_image_url = db.Column(db.String(500), nullable=True)
    credits = db.Column(db.Integer, default=0, nullable=False)
    welcome_email_sent = db.Column(db.Boolean, default=False, nullable=False)
    referral_code = db.Column(db.String(16), unique=True, nullable=True, index=True)
    referred_by_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)
    referral_bonus_given = db.Column(db.Boolean, default=False, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    verification_token = db.Column(db.String(64), nullable=True, index=True)
    password_reset_token = db.Column(db.String(64), nullable=True, index=True)
    password_reset_expires = db.Column(db.DateTime, nullable=True)
    auth_provider = db.Column(db.String(20), default="email", nullable=False)
    id_hash = db.Column(db.String(64), unique=True, nullable=True, index=True)
    id_type = db.Column(db.String(20), nullable=True)
    id_scan_url = db.Column(db.String(1000), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    is_staff = db.Column(db.Boolean, default=False, nullable=False)
    is_writer = db.Column(db.Boolean, default=False, nullable=False)
    account_status = db.Column(db.String(20), default="active", nullable=False)
    free_trial_used = db.Column(db.Boolean, default=False, nullable=False)
    free_trial_count = db.Column(db.Integer, default=0, nullable=False)
    review_prompted = db.Column(db.Boolean, default=False, nullable=False)
    flag_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def display_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.email or "Student"

    @property
    def active_plan_name(self):
        """Return the current active subscription plan name, or None."""
        sub = next(
            (s for s in (self.subscriptions if hasattr(self, "subscriptions") else [])
             if s.status == "active" and s.end_date and s.end_date > datetime.utcnow()),
            None,
        )
        if sub:
            return sub.plan.capitalize()
        return None


class Assignment(db.Model):
    __tablename__ = "assignments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False, index=True)
    topic = db.Column(db.Text, nullable=False)
    pages = db.Column(db.Integer, nullable=False)
    word_count = db.Column(db.Integer, nullable=False)
    num_sources = db.Column(db.Integer, nullable=False)
    style = db.Column(db.String(50), nullable=False)
    education_level = db.Column(db.String(50), nullable=False)
    credit_cost = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(50), default="draft", nullable=False)
    progress_step = db.Column(db.String(120), default="Pending", nullable=False)
    progress_percent = db.Column(db.Integer, default=0, nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    docx_url = db.Column(db.String(1000), nullable=True)
    docx_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    assignment_type = db.Column(db.String(20), default="standard", nullable=False)
    instruction_image_url = db.Column(db.String(1000), nullable=True)
    humanize_style = db.Column(db.String(30), default="academic", nullable=False)
    humanize_model = db.Column(db.String(20), default="advanced", nullable=False)
    paper_text = db.Column(db.Text, nullable=True)
    rubric_url = db.Column(db.String(1000), nullable=True)
    marking_result = db.Column(db.Text, nullable=True)
    course_name = db.Column(db.String(255), nullable=True)
    student_name = db.Column(db.String(255), nullable=True)
    instructor_name = db.Column(db.String(255), nullable=True)
    school_name = db.Column(db.String(255), nullable=True)
    due_date = db.Column(db.String(50), nullable=True)

    sources = db.relationship("Source", backref="assignment", cascade="all, delete-orphan")
    logs = db.relationship("PipelineLog", backref="assignment", cascade="all, delete-orphan")


class Source(db.Model):
    __tablename__ = "sources"
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False, index=True)
    title = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    url = db.Column(db.String(1000), nullable=True)
    raw_text = db.Column(db.Text, nullable=True)
    authors = db.Column(db.String(500), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    is_user_provided = db.Column(db.Boolean, default=False)
    apa_intext    = db.Column(db.Text, nullable=True)
    apa_reference = db.Column(db.Text, nullable=True)
    annotation    = db.Column(db.Text, nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)


class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False, index=True)
    amount_usd_cents = db.Column(db.Integer, nullable=False)
    credits = db.Column(db.Integer, nullable=False, default=0)
    provider = db.Column(db.String(50), default="stripe")
    provider_ref = db.Column(db.String(255), nullable=True, index=True)
    merchant_ref = db.Column(db.String(255), nullable=True, index=True)
    status = db.Column(db.String(50), default="pending", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)


class Subscription(db.Model):
    """One row per subscription period purchased."""
    __tablename__ = "subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False, index=True)
    plan = db.Column(db.String(20), nullable=False)           # basic / standard / unlimited
    billing_period = db.Column(db.String(20), nullable=False) # monthly / halfyear / yearly
    status = db.Column(db.String(20), default="pending", nullable=False)  # pending / active / expired / cancelled
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    price_paid_cents = db.Column(db.Integer, nullable=False, default=0)
    discount_pct = db.Column(db.Integer, default=0, nullable=False)
    stripe_session_id = db.Column(db.String(255), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="subscriptions")

    PLAN_LABELS = {
        "basic": "Basic",
        "standard": "Standard",
        "unlimited": "Unlimited",
    }
    PERIOD_LABELS = {
        "monthly": "Monthly",
        "halfyear": "6 Months",
        "yearly": "Yearly",
    }

    @property
    def plan_label(self):
        return self.PLAN_LABELS.get(self.plan, self.plan.title())

    @property
    def period_label(self):
        return self.PERIOD_LABELS.get(self.billing_period, self.billing_period.title())

    @property
    def is_active(self):
        return self.status == "active" and self.end_date and self.end_date > datetime.utcnow()


class DailyUsage(db.Model):
    """Tracks how many AI assignments a user has started per calendar day."""
    __tablename__ = "daily_usage"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    count = db.Column(db.Integer, default=0, nullable=False)

    __table_args__ = (db.UniqueConstraint("user_id", "date", name="uq_daily_usage_user_date"),)
    user = db.relationship("User", backref="daily_usages")


class PipelineLog(db.Model):
    __tablename__ = "pipeline_logs"
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False, index=True)
    step = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(50), default="info")
    detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UserNotification(db.Model):
    __tablename__ = "user_notifications"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.String, db.ForeignKey("users.id"), nullable=False, index=True)
    type       = db.Column(db.String(30), nullable=False)
    title      = db.Column(db.String(120), nullable=False)
    body       = db.Column(db.Text, nullable=False)
    is_read    = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChatSession(db.Model):
    __tablename__ = "chat_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(20), default="open", nullable=False)
    has_human = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref="chat_sessions")
    messages = db.relationship(
        "ChatMessage", backref="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("chat_sessions.id"),
                           nullable=False, index=True)
    sender = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    read_by_staff = db.Column(db.Boolean, default=False, nullable=False)
    read_by_user  = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class HumanOrder(db.Model):
    __tablename__ = "human_orders"
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.String, db.ForeignKey("users.id"), nullable=False, index=True)
    writer_id   = db.Column(db.String, db.ForeignKey("users.id"), nullable=True)

    title          = db.Column(db.String(500), nullable=False)
    subject        = db.Column(db.String(200), nullable=False)
    instructions   = db.Column(db.Text, nullable=False)
    academic_level = db.Column(db.String(50),  nullable=False)
    format_style   = db.Column(db.String(30),  nullable=False)
    num_pages      = db.Column(db.Integer,     nullable=False)
    num_references = db.Column(db.Integer,     default=0, nullable=False)
    deadline       = db.Column(db.DateTime,    nullable=False)
    priority       = db.Column(db.String(20),  default="standard", nullable=False)

    credits_per_page       = db.Column(db.Integer, default=0, nullable=False)
    credits_paid           = db.Column(db.Integer, nullable=False, default=0)
    status                 = db.Column(db.String(30), default="pending", nullable=False)
    writer_confirmed_human = db.Column(db.Boolean, default=False, nullable=False)

    final_file_url  = db.Column(db.String(1000), nullable=True)
    final_file_name = db.Column(db.String(255),  nullable=True)

    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    student  = db.relationship("User", foreign_keys=[user_id],   backref="human_orders")
    writer   = db.relationship("User", foreign_keys=[writer_id],  backref="claimed_orders")
    messages = db.relationship("HumanOrderMessage", backref="order",
                               cascade="all, delete-orphan", order_by="HumanOrderMessage.id")
    files    = db.relationship("HumanOrderFile", backref="order", cascade="all, delete-orphan")

    STATUS_LABELS = {
        "pending":     "Pending",
        "assigned":    "Assigned",
        "in_progress": "In Progress",
        "completed":   "Completed",
        "delivered":   "Delivered",
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status.title())


class HumanOrderMessage(db.Model):
    __tablename__ = "human_order_messages"
    id          = db.Column(db.Integer, primary_key=True)
    order_id    = db.Column(db.Integer, db.ForeignKey("human_orders.id"), nullable=False, index=True)
    sender_id   = db.Column(db.String,  db.ForeignKey("users.id"), nullable=False)
    sender_role = db.Column(db.String(20), nullable=False)
    content     = db.Column(db.Text, nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    sender      = db.relationship("User", foreign_keys=[sender_id])


class HumanOrderFile(db.Model):
    __tablename__ = "human_order_files"
    id          = db.Column(db.Integer, primary_key=True)
    order_id    = db.Column(db.Integer, db.ForeignKey("human_orders.id"), nullable=False, index=True)
    uploader_id = db.Column(db.String,  db.ForeignKey("users.id"), nullable=False)
    file_url    = db.Column(db.String(1000), nullable=False)
    file_name   = db.Column(db.String(255),  nullable=False)
    file_type   = db.Column(db.String(20),   nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    uploader    = db.relationship("User", foreign_keys=[uploader_id])


class JobDocument(db.Model):
    __tablename__ = "job_documents"
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.String, db.ForeignKey("users.id"), nullable=False, index=True)
    doc_type     = db.Column(db.String(60),  nullable=False)
    doc_label    = db.Column(db.String(120), nullable=False)
    details_json = db.Column(db.Text, nullable=False)
    content      = db.Column(db.Text, nullable=True)
    status       = db.Column(db.String(20), default="pending")
    docx_url     = db.Column(db.String(1000), nullable=True)
    docx_filename = db.Column(db.String(255),  nullable=True)
    pdf_url      = db.Column(db.String(1000), nullable=True)
    pdf_filename = db.Column(db.String(255),  nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    user         = db.relationship("User", backref="job_documents")


class OAuth(db.Model):
    __tablename__ = "oauth"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String, nullable=True, index=True)
    browser_session_key = db.Column(db.String, nullable=False, index=True)
    provider = db.Column(db.String, nullable=False)
    token = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AIRemovalJob(db.Model):
    """Tracks AI-removal requests submitted by students when AI score > 1%."""
    __tablename__ = "ai_removal_jobs"

    id             = db.Column(db.Integer, primary_key=True)
    assignment_id  = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False, index=True)
    user_id        = db.Column(db.String,  db.ForeignKey("users.id"),       nullable=False, index=True)
    writer_id      = db.Column(db.String,  db.ForeignKey("users.id"),       nullable=True)

    # What the student submitted
    original_text      = db.Column(db.Text,  nullable=False)
    original_ai_score  = db.Column(db.Float, nullable=False)
    word_count         = db.Column(db.Integer, nullable=True)
    student_notes      = db.Column(db.Text, nullable=True)

    # What the writer returns
    final_text         = db.Column(db.Text,         nullable=True)
    final_file_url     = db.Column(db.String(1000),  nullable=True)
    final_file_name    = db.Column(db.String(255),   nullable=True)
    final_ai_score     = db.Column(db.Float,         nullable=True)

    # Workflow
    # pending → assigned → completed
    status        = db.Column(db.String(20), default="pending", nullable=False, index=True)
    deadline      = db.Column(db.DateTime, nullable=False)
    submitted_at  = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at  = db.Column(db.DateTime, nullable=True)

    assignment = db.relationship("Assignment", backref="ai_removal_jobs")
    student    = db.relationship("User", foreign_keys=[user_id],  backref="ai_removal_submissions")
    writer     = db.relationship("User", foreign_keys=[writer_id], backref="ai_removal_assignments")

    @property
    def deadline_minutes(self):
        """Minutes until deadline (negative if overdue)."""
        delta = self.deadline - datetime.utcnow()
        return int(delta.total_seconds() / 60)

    @property
    def is_overdue(self):
        return datetime.utcnow() > self.deadline

    STATUS_LABELS = {
        "pending":   "Waiting for Writer",
        "assigned":  "Writer Assigned",
        "completed": "Completed",
    }


class Review(db.Model):
    """Student star review left after an assignment is completed."""
    __tablename__ = "reviews"

    id            = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"),
                              nullable=False, unique=True, index=True)
    user_id       = db.Column(db.String, db.ForeignKey("users.id"),
                              nullable=False, index=True)
    rating        = db.Column(db.Integer, nullable=False)   # 1–5
    reason        = db.Column(db.String(200), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    assignment = db.relationship("Assignment", backref=db.backref("review", uselist=False))
    student    = db.relationship("User", backref="reviews")
